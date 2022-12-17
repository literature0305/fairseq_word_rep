#!/usr/bin/env bash

# Binarize the dataset
TEXT=examples/translation/wmt17_en_de
TEXT_word=examples/translation/wmt17_en_de_word

# Get subword-level word-alignments
if [ -d $TEXT_word ]; then
    echo "$TEXT_word exist"
else
    echo "$TEXT_word does not exist, generate it"
    mkdir $TEXT_word
    python 20_align_word_as_subword_order_ver2.py $TEXT $TEXT_word
fi

fairseq-preprocess \
    --source-lang de --target-lang en \
    --trainpref $TEXT/train --validpref $TEXT/valid --testpref $TEXT/test \
    --destdir data-bin/wmt17_de_en --thresholdtgt 0 --thresholdsrc 0 \
    --workers 20

fairseq-preprocess \
    --source-lang de --target-lang en \
    --trainpref $TEXT_word/train --validpref $TEXT_word/valid --testpref $TEXT_word/test \
    --destdir data-bin/wmt17_de_en_word --thresholdtgt 0 --thresholdsrc 0 \
    --workers 20

# train    
# mkdir -p checkpoints/transformer_wmt_en_de
CUDA_VISIBLE_DEVICES=0 fairseq-train data-bin/wmt17_de_en \
    --arch transformer_wmt_en_de --share-decoder-input-output-embed \
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

# # # evaluation
# fairseq-generate data-bin/wmt17_de_en \
#     --path checkpoints/checkpoint_best.pt \