#!/usr/bin/env bash
TEXT=examples/translation/iwslt14.tokenized.de-en
TEXT_word=examples/translation/iwslt14.tokenized.de-en_word

# Get subword-level word-alignments
if [ -d $TEXT_word ]; then
    echo "$TEXT_word exist"
else
    mkdir $TEXT_word
    python 20_align_word_as_subword_order_ver2.py $TEXT $TEXT_word
fi

# Preprocess/binarize the data
fairseq-preprocess --source-lang de --target-lang en \
    --trainpref $TEXT/train --validpref $TEXT/valid --testpref $TEXT/test \
    --destdir data-bin/iwslt14.tokenized.de-en \
    --workers 20

fairseq-preprocess --source-lang de --target-lang en \
    --trainpref $TEXT_word/train --validpref $TEXT_word/valid --testpref $TEXT_word/test \
    --destdir data-bin/iwslt14.tokenized.de-en_word \
    --workers 20

# train
CUDA_VISIBLE_DEVICES=0 fairseq-train \
    data-bin/iwslt14.tokenized.de-en \
    --arch transformer_iwslt_de_en --share-decoder-input-output-embed \
    --optimizer adam --adam-betas '(0.9, 0.98)' --clip-norm 0.0 \
    --lr 5e-4 --lr-scheduler inverse_sqrt --warmup-updates 4000 \
    --dropout 0.3 --weight-decay 0.0001 \
    --criterion label_smoothed_cross_entropy --label-smoothing 0.1 \
    --max-tokens 4096 \
    --eval-bleu \
    --eval-bleu-args '{"beam": 5, "max_len_a": 1.2, "max_len_b": 10}' \
    --eval-bleu-detok moses \
    --eval-bleu-remove-bpe \
    --eval-bleu-print-samples \
    --best-checkpoint-metric bleu --maximize-best-checkpoint-metric

# evaluation
fairseq-generate data-bin/iwslt14.tokenized.de-en \
    --path checkpoints/checkpoint_best.pt \
    --batch-size 128 --beam 5 --remove-bpe