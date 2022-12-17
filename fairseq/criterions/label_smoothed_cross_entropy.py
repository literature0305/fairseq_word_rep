# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import math
from dataclasses import dataclass, field

import torch
from omegaconf import II

from fairseq import metrics, utils
from fairseq.criterions import FairseqCriterion, register_criterion
from fairseq.dataclass import FairseqDataclass


@dataclass
class LabelSmoothedCrossEntropyCriterionConfig(FairseqDataclass):
    label_smoothing: float = field(
        default=0.0,
        metadata={"help": "epsilon for label smoothing, 0 means no label smoothing"},
    )
    report_accuracy: bool = field(
        default=False,
        metadata={"help": "report accuracy metric"},
    )
    ignore_prefix_size: int = field(
        default=0,
        metadata={"help": "Ignore first N tokens"},
    )
    sentence_avg: bool = II("optimization.sentence_avg")


def label_smoothed_nll_loss(lprobs, target, epsilon, ignore_index=None, reduce=True):
    if target.dim() == lprobs.dim() - 1:
        target = target.unsqueeze(-1)
    nll_loss = -lprobs.gather(dim=-1, index=target)
    smooth_loss = -lprobs.sum(dim=-1, keepdim=True)
    if ignore_index is not None:
        pad_mask = target.eq(ignore_index)
        nll_loss.masked_fill_(pad_mask, 0.0)
        smooth_loss.masked_fill_(pad_mask, 0.0)
    else:
        nll_loss = nll_loss.squeeze(-1)
        smooth_loss = smooth_loss.squeeze(-1)
    if reduce:
        nll_loss = nll_loss.sum()
        smooth_loss = smooth_loss.sum()
    eps_i = epsilon / (lprobs.size(-1) - 1)
    loss = (1.0 - epsilon - eps_i) * nll_loss + eps_i * smooth_loss
    return loss, nll_loss


@register_criterion(
    "label_smoothed_cross_entropy", dataclass=LabelSmoothedCrossEntropyCriterionConfig
)
class LabelSmoothedCrossEntropyCriterion(FairseqCriterion):
    def __init__(
        self,
        task,
        sentence_avg,
        label_smoothing,
        ignore_prefix_size=0,
        report_accuracy=False,
    ):
        super().__init__(task)
        self.sentence_avg = sentence_avg
        self.eps = label_smoothing
        self.ignore_prefix_size = ignore_prefix_size
        self.report_accuracy = report_accuracy

    def forward(self, model, sample, reduce=True, update_num=None):
        """Compute the loss for the given sample.

        Returns a tuple with three elements:
        1) the loss
        2) the sample size, which is used as the denominator for the gradient
        3) logging outputs to display while training
        """
        net_output = model(**sample["net_input"])

        if "target_word" in sample:
            loss, nll_loss = self.compute_loss(model, net_output, sample, reduce=reduce, word_level_target=sample["target_word"], update_num=update_num)
        else:
            loss, nll_loss = self.compute_loss(model, net_output, sample, reduce=reduce)

        sample_size = (
            sample["target"].size(0) if self.sentence_avg else sample["ntokens"]
        )
        logging_output = {
            "loss": loss.data,
            "nll_loss": nll_loss.data,
            "ntokens": sample["ntokens"],
            "nsentences": sample["target"].size(0),
            "sample_size": sample_size,
        }
        if self.report_accuracy:
            n_correct, total = self.compute_accuracy(model, net_output, sample)
            logging_output["n_correct"] = utils.item(n_correct.data)
            logging_output["total"] = utils.item(total.data)
        return loss, sample_size, logging_output

    def get_lprobs_and_target(self, model, net_output, sample):
        lprobs = model.get_normalized_probs(net_output, log_probs=True)
        target = model.get_targets(sample, net_output)
        if self.ignore_prefix_size > 0:
            # lprobs: B x T x C
            lprobs = lprobs[:, self.ignore_prefix_size :, :].contiguous()
            target = target[:, self.ignore_prefix_size :].contiguous()
        return lprobs.view(-1, lprobs.size(-1)), target.view(-1)

    def compute_loss(self, model, net_output, sample, reduce=True, word_level_target=None, update_num=None):
        lprobs, target = self.get_lprobs_and_target(model, net_output, sample)
        loss, nll_loss = label_smoothed_nll_loss(
            lprobs,
            target,
            self.eps,
            ignore_index=self.padding_idx,
            reduce=False,
        )

        if word_level_target is not None:
            # get auxiliary word embedding layer output
            net_output_word = net_output[1]["x_word"]
            n_batch, n_time, _ = net_output_word.size()

            # normalize net_output_word
            norm = torch.norm(net_output_word, dim=-1)
            net_output_word = net_output_word / norm.unsqueeze(-1)

            # make one-hot word-level target
            assert word_level_target.size() == net_output_word.sum(-1).size()
            assert (word_level_target < 0).sum() == 0
            word_level_target = torch.nn.functional.one_hot(word_level_target, num_classes= - 1).type(torch.FloatTensor).to(net_output_word.device) # B,T,f
            
            # get word-level similarity matrix (target, model_output)
            word_level_similarity_matrix_positive = torch.matmul(word_level_target, word_level_target.transpose(-2, -1)) # B,T,T
            word_level_similarity_matrix = torch.matmul(net_output_word, net_output_word.transpose(-2,-1)) # B,T,T
            global_min = word_level_similarity_matrix.min()

            # get mask for padding area (B,T), diagonal elements (T,T) -> (B,T,T)
            non_pad_area = (self.padding_idx != target).view(n_batch, n_time).unsqueeze(-1)
            inv_identity_matrix = 1-torch.eye(n_time).to(net_output_word.device).unsqueeze(0)
            mask_pad_eye = non_pad_area * inv_identity_matrix

            # remove diagonal elements & padding (B,T,T)
            word_level_similarity_matrix_positive = word_level_similarity_matrix_positive * mask_pad_eye
            word_level_similarity_matrix = word_level_similarity_matrix * mask_pad_eye + (1-mask_pad_eye) * global_min

            # normalize
            word_level_similarity_matrix = torch.softmax(word_level_similarity_matrix, dim=-1)

            # get loss_word
            loss_word = (torch.log((word_level_similarity_matrix_positive.sum(-1).unsqueeze(-1) * word_level_similarity_matrix + 0.00001)) * word_level_similarity_matrix_positive).sum(-1).unsqueeze(-1)
            loss_word = loss_word / ((word_level_similarity_matrix_positive).sum(-1) + 1).unsqueeze(-1)

            # normalization considering batch-wise positive sample existance (to alleviate token size dependency problem)
            num_positive = (word_level_similarity_matrix_positive.sum(-1) > 0).sum()
            num_total_sample = (self.padding_idx != target).sum()
            loss_word = loss_word / num_positive * num_total_sample

            loss = loss.view(loss_word.size())

            # summation
            alpha_word2 = 0.01
            # if update_num is not None:
            #     alpha_word2 = alpha_word2 * update_num / 50000 # 100000
            if update_num is not None and update_num < 12000:
                alpha_word2 = 0
            if torch.randperm(200)[0] == 0:
                print('alpha_word2:', alpha_word2, 'loss:', loss.sum().item(), 'loss_word:', - loss_word.sum().item(), 'num_positive:', num_positive, 'num_total_sample:', num_total_sample)

            loss = (loss - alpha_word2 * loss_word).sum()
        else:
            loss = loss.sum()

        return loss, nll_loss.sum()

    def compute_accuracy(self, model, net_output, sample):
        lprobs, target = self.get_lprobs_and_target(model, net_output, sample)
        mask = target.ne(self.padding_idx)
        n_correct = torch.sum(
            lprobs.argmax(1).masked_select(mask).eq(target.masked_select(mask))
        )
        total = torch.sum(mask)
        return n_correct, total

    @classmethod
    def reduce_metrics(cls, logging_outputs) -> None:
        """Aggregate logging outputs from data parallel training."""
        loss_sum = sum(log.get("loss", 0) for log in logging_outputs)
        nll_loss_sum = sum(log.get("nll_loss", 0) for log in logging_outputs)
        ntokens = sum(log.get("ntokens", 0) for log in logging_outputs)
        sample_size = sum(log.get("sample_size", 0) for log in logging_outputs)

        metrics.log_scalar(
            "loss", loss_sum / sample_size / math.log(2), sample_size, round=3
        )
        metrics.log_scalar(
            "nll_loss", nll_loss_sum / ntokens / math.log(2), ntokens, round=3
        )
        metrics.log_derived(
            "ppl", lambda meters: utils.get_perplexity(meters["nll_loss"].avg)
        )

        total = utils.item(sum(log.get("total", 0) for log in logging_outputs))
        if total > 0:
            metrics.log_scalar("total", total)
            n_correct = utils.item(
                sum(log.get("n_correct", 0) for log in logging_outputs)
            )
            metrics.log_scalar("n_correct", n_correct)
            metrics.log_derived(
                "accuracy",
                lambda meters: round(
                    meters["n_correct"].sum * 100.0 / meters["total"].sum, 3
                )
                if meters["total"].sum > 0
                else float("nan"),
            )

    @staticmethod
    def logging_outputs_can_be_summed() -> bool:
        """
        Whether the logging outputs returned by `forward` can be summed
        across workers prior to calling `reduce_metrics`. Setting this
        to True will improves distributed training speed.
        """
        return True
