#!/usr/bin/env bash

# Binarize the dataset
TEXT=examples/translation/wmt17_en_de
TEXT_word=examples/translation/wmt17_en_de_word

# # # evaluation
fairseq-generate data-bin/wmt17_de_en \
    --path checkpoints/checkpoint_best.pt \