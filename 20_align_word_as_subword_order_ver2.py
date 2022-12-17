import os
import sys
if len(sys.argv) != 3:
    raise ValueError('USAGE: python 20_align_word_as_subword_order.py PATH_IN PATH_OUT')
input_subword_dir = sys.argv[1]
output_word_dir = sys.argv[2]

input_files=['train.en','test.de', 'test.en', 'train.de', 'train.en', 'valid.de', 'valid.en']

if os.path.isdir(output_word_dir):
    pass
else:
    os.system("mkdir " + output_word_dir)

# if True: return word-index else: return word-alignments (indexed by word set in utterance)
return_word_idx = False

for input_file in input_files:
    filename_subword = input_subword_dir + '/' + input_file
    filename_output = output_word_dir + '/' + input_file

    with open(filename_subword, 'r') as f:
        lines_subwords = f.readlines()

    new_lines_to_write = []

    for idx, subwords in enumerate(lines_subwords):
        # words = lines_words[idx].replace('\n','').replace('@@','').strip().split(' ')
        words = subwords.replace('\n','').replace('@@ ','').strip().split(' ')
        subwords = subwords.replace('\n','').replace('@@','').strip().split(' ')
        word_dict = {}

        for jdx, subword in enumerate(subwords):
            if jdx == 0:
                new_line = []
                if return_word_idx:
                    new_line.append(words[0])
                else:
                    word_dict[words[0]] = 0
                    new_line.append('0')
                len_subword = len(subwords[0])
                len_word = len(words[0])
                idx_word = 0
            else:
                # fix idx_word, len_word, len_subword
                if len_subword == len_word:
                    idx_word = idx_word + 1
                    len_word = len_word + len(words[idx_word])
                    len_subword = len_subword + len(subword)
                elif len_subword < len_word:
                    len_subword = len_subword + len(subword)
                else:
                    print('word:', words)
                    print('subwords:', subwords)
                    raise ValueErorr('ERROR: len_subword > len_word')

                # append word
                if return_word_idx:
                    new_line.append(words[idx_word])
                else:
                    if words[idx_word] in word_dict:
                        new_line.append(str(word_dict[words[idx_word]]))
                    else:
                        word_dict[words[idx_word]] = idx_word
                        new_line.append(str(idx_word))

        assert len(new_line) == len(subwords)
        if return_word_idx:
            assert set(new_line) == set(words)

        new_line = ' '.join(new_line) + '\n'
        new_lines_to_write.append(new_line)

    with open(filename_output, 'w') as f:
        f.writelines(new_lines_to_write)