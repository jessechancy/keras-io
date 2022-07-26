"""
Title: Simple GPT Text Generation with KerasNLP transformers
Author: [Jesse Chan](https://github.com/jessechancy)
Date created: 2022/07/25
Last modified: 2022/07/25
Description: Using KerasNLP transformers to train a mini-GPT model for text generation.
"""

"""
## Introduction

In this example, we will use KerasNLP layers to build a scaled down Generative
Pre-trained (GPT) model. GPT is a transformer based model that allows you to generate
sophisticated text from a small input.

We will train the model on the [simplebooks-92](https://arxiv.org/abs/1911.12391) corpus,
which is a dataset made from several novels. It is a good dataset for this example since
it has a small vocabulary and high word frequency, which is beneficial when training a
model with few parameters.

This example combines concepts from [Text generation with a miniature GPT](https://keras.io/examples/generative/text_generation_with_miniature_gpt/)
with KerasNLP abstractions. We will demonstrate how KerasNLP tokenization, layers and
metrics simplify the training
process, and then show how to generate output text using sampling utilities.

Note: If you are running this on a colab make sure to enable GPU runtime for faster
training performance.
"""

"""
# Mini-GPT Text Generation with KerasNLP transformers

This example requires KerasNLP. You can install it via the following command: `pip
install keras-nlp`
"""

"""
## Imports
"""

import os
import keras_nlp
import tensorflow as tf
from tensorflow import keras

"""
## Settings / Hyperparameters
"""

# Data
BATCH_SIZE = 64
SEQ_LEN = 128
MIN_TRAINING_SEQ_LEN = 100

# Model
EMBED_DIM = 256
FEED_FORWARD_DIM = 256
NUM_HEADS = 3
NUM_LAYERS = 2
VOCAB_SIZE = 5000  # Limits parameters in model.

# Training
LEARNING_RATE = 5e-4
EPOCHS = 6

# Inference
NUM_TOKENS_TO_GENERATE = 80

"""
## Load Data

Now, let's download the dataset! The SimpleBooks dataset has a small vocabulary, which
makes it easier to fit a simple model on.
"""

keras.utils.get_file(
    origin="https://dldata-public.s3.us-east-2.amazonaws.com/simplebooks.zip",
    extract=True,
)
dir = os.path.expanduser("~/.keras/datasets/simplebooks/")

# Load simplebooks-92 train set and filter out short lines.
raw_train_ds = (
    tf.data.TextLineDataset(dir + "simplebooks-92-raw/train.txt")
    .filter(lambda x: tf.strings.length(x) > MIN_TRAINING_SEQ_LEN)
    .batch(BATCH_SIZE)
    .shuffle(buffer_size=256)
)

# Load simplebooks-92 validation set and filter out short lines.
raw_val_ds = (
    tf.data.TextLineDataset(dir + "simplebooks-92-raw/valid.txt")
    .filter(lambda x: tf.strings.length(x) > MIN_TRAINING_SEQ_LEN)
    .batch(BATCH_SIZE)
)

"""
## Train Tokenizer

We train the tokenizer from the training dataset for a vocabulary size of `VOCAB_SIZE`,
which is a tuned hyperparameter. We want to limit the vocabulary as much as possible, as
we will see later on
that it has a large affect on the number of model parameters. We also don't want to take
too few vocabulary, or there would be too many out of vocabulary (OOV) sub-words. In
addition, three tokens are reserved in the vocabulary:
- `"[PAD]"` for padding sequences to `SEQ_LEN`. This token has index 0 in both
`reserved_tokens` and `vocab`, since `WordPieceTokenizer` (and other layers) consider
`0`/`vocab[0]` as the default padding.
- `"[UNK]"` for OOV sub-words, which should match the default `oov_token="[UNK]"` in
`WordPieceTokenizer`.
- `"[BOS]"` stands for beginning of sentence, but here technically it is a token
representing the beginning of each line of training data.
"""

# Train tokenizer vocabulary
vocab = keras_nlp.tokenizers.compute_word_piece_vocabulary(
    raw_train_ds,
    vocabulary_size=VOCAB_SIZE,
    reserved_tokens=["[PAD]", "[UNK]", "[BOS]"],
)

"""
## Load Tokenizer

We use the vocabulary data to initialize
`keras_nlp.tokenizers.WordPieceTokenizer`. WordPieceTokenizer is an efficient
implementation of the WordPiece algorithm used by BERT and other models. It will strip,
lower-case and do other un-reversable preprocessing operations.
"""

tokenizer = keras_nlp.tokenizers.WordPieceTokenizer(
    vocabulary=vocab, sequence_length=SEQ_LEN
)

"""
## Tokenize Data

We pre-process the dataset by tokenizing and splitting it into `features` and `labels`.
"""

# packer adds a start token
start_packer = keras_nlp.layers.StartEndPacker(
    sequence_length=SEQ_LEN,
    start_value=tokenizer.token_to_id("[BOS]"),
)


def preprocess(inputs):
    outputs = tokenizer(inputs)
    features = start_packer(outputs)
    labels = outputs
    return features, labels


# Tokenize and split into train and label sequences.
train_ds = raw_train_ds.map(preprocess, num_parallel_calls=tf.data.AUTOTUNE).prefetch(
    tf.data.AUTOTUNE
)
val_ds = raw_val_ds.map(preprocess, num_parallel_calls=tf.data.AUTOTUNE).prefetch(
    tf.data.AUTOTUNE
)

"""
## Model

We create our scaled down GPT model with the following layers:

- One `keras_nlp.layers.TokenAndPositionEmbedding` layer, which combines the embedding
for the token and its position.
- Multiple `keras_nlp.layers.TransformerDecoder` layers, with the default causal masking.
The layer has no cross-attention when run with decoder sequence only.
- One output dense linear layer
"""

inputs = keras.layers.Input(shape=(None,), dtype=tf.int32)
# Embedding.
embedding_layer = keras_nlp.layers.TokenAndPositionEmbedding(
    vocabulary_size=VOCAB_SIZE,
    sequence_length=SEQ_LEN,
    embedding_dim=EMBED_DIM,
    mask_zero=True,
)
x = embedding_layer(inputs)
# Transformer decoders.
for _ in range(NUM_LAYERS):
    decoder_layer = keras_nlp.layers.TransformerDecoder(
        num_heads=NUM_HEADS,
        intermediate_dim=FEED_FORWARD_DIM,
    )
    x = decoder_layer(x)  # Giving one argument only skips cross-attention.
# Output.
outputs = keras.layers.Dense(VOCAB_SIZE)(x)
model = keras.Model(inputs=inputs, outputs=outputs)
loss_fn = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True)
perplexity = keras_nlp.metrics.Perplexity(from_logits=True, mask_token_id=0)
model.compile(optimizer="adam", loss=loss_fn, metrics=[perplexity])

"""
Let's take a look at our model summary - a large majority of the
parameters are in the `token_and_position_embedding` and the output `dense` layer! This
means
that the vocabulary size (`VOCAB_SIZE`) has a large affect on the size of the model,
while the number of transformer decoder layers (`NUM_LAYERS`) doesn't affect it as much.
"""

model.summary()

"""
## Training

Now that we have our model, let's train it with the `fit()` method.
"""

model.fit(train_ds, validation_data=val_ds, verbose=2, epochs=EPOCHS)

"""
## Inference

With our trained model, we can test it out to gauge it's performance. Since this model is
built with a `"[BOS]"` token, we can have an empty starting prompt for text generation.
"""

# Unpadded bos token.
prompt_tokens = tf.convert_to_tensor([tokenizer.token_to_id("[BOS]")])

"""
We will use the `keras_nlp.utils` library for inference. Every text generation
utility would require a `token_logits_fn()` wrapper around the model. This wrapper takes
in an unpadded token sequence, and requires the logits of the next token as the output.
"""


def token_logits_fn(inputs):
    cur_len = inputs.shape[1]
    output = model(inputs)
    return output[:, cur_len - 1, :]  # return next token logits


"""
Creating the wrapper function is the most complex part of using these functions. Now that
it's done, let's test out the different utilties, starting with greedy search.
"""

"""
### Greedy Search

We greedily pick the most probable token at each timestep. In other words, we get the
argmax of the model output.
"""

output_tokens = keras_nlp.utils.greedy_search(
    token_logits_fn,
    prompt_tokens,
    max_length=NUM_TOKENS_TO_GENERATE,
)
txt = tokenizer.detokenize(output_tokens)
print(f"Greedy search generated text: \n{txt}\n")

"""
As we can see, greedy search starts out making some sense, but quickly starts repeating
itself. This is a common problem with text generation that can be fixed by some of the
probabilistic text generation utilities shown later on!
"""

"""
### Beam Search

At a high-level, beam search keeps track of the `num_beams` most probable sequences at
each timestep, and predicts the best next token from all sequences. It is an improvement
over greedy search since it stores more possibilities. However, it is less efficient than
greedy search since it has to compute and store multiple potential sequences.

Note: beam search with `num_beams=1` is identical to greedy search
"""

output_tokens = keras_nlp.utils.beam_search(
    token_logits_fn,
    prompt_tokens,
    max_length=NUM_TOKENS_TO_GENERATE,
    num_beams=10,
    from_logits=True,
)
txt = tokenizer.detokenize(output_tokens)
print(f"Beam search generated text: \n{txt}\n")

"""
Similar to greedy search, beam search quickly starts repeating itself, since it is still
a deterministic method.
"""

"""
### Random Search

Random search is our first probabilistic method. At each time step, it samples the next
token using the softmax probabilities provided by the model.
"""

output_tokens = keras_nlp.utils.random_search(
    token_logits_fn,
    prompt_tokens,
    max_length=NUM_TOKENS_TO_GENERATE,
    from_logits=True,
)
txt = tokenizer.detokenize(output_tokens)
print(f"Random search generated text: \n{txt}\n")

"""
Voila, no repetitions! However, with random search, we may see some nonsensical words
appearing since any word in the vocabulary has a chance of appearing with this sampling
method. This is fixed by our next search utility, top-k search.
"""

"""
### Top-K Search

Similar to random search, we sample the next token from the probability distribution
provided by the model. The only difference is that here, we select out the top `k` most
probable tokens, and distribute the probabiltiy mass over them before sampling. This way,
we won't be sampling from low probability tokens, and hence we would have less
nonsensical words!
"""

output_tokens = keras_nlp.utils.top_k_search(
    token_logits_fn,
    prompt_tokens,
    max_length=NUM_TOKENS_TO_GENERATE,
    k=10,
    from_logits=True,
)
txt = tokenizer.detokenize(output_tokens)
print(f"Top-K search generated text: \n{txt}\n")

"""
### Top-P Search

Even with the top-k search, there is something to improve upon. With top-k search, the
number `k` is fixed, which means it selects the same number of tokens for any probability
distribution. Consider two scenarios, one where the probability mass is concentrated over
2 words and another where the probability mass is evenly concentrated across 10. Should
we choose `k=2` or `k=10`? There is not a one size fits all `k` here.

This is where top-p search comes in! Instead of choosing a `k`, we choose a probability
`p` that we want the probabilities of the top tokens to sum up to. This way, we can
dynamically adjust the `k` based on the probability distribution. By setting `p=0.9`, if
90% of the probability mass is concentrated on the top 2 tokens, we can filter out the
top 2 tokens to sample from. If instead the 90% is distributed over 10 tokens, it will
similarly filter out the top 10 tokens to sample from.
"""

output_tokens = keras_nlp.utils.top_p_search(
    token_logits_fn,
    prompt_tokens,
    max_length=NUM_TOKENS_TO_GENERATE,
    p=0.5,
    from_logits=True,
)
txt = tokenizer.detokenize(output_tokens)
print(f"Top-P search generated text: \n{txt}\n")

"""
### Using Callbacks

We can also wrap the utilities in a callback, which allows you to print out a prediction
sequence for every epoch of the model! Here is an example of a callback for top-k search:
"""


class TopKTextGenerator(keras.callbacks.Callback):
    """A callback to generate text from a trained model using top-k."""

    def __init__(self, k):
        self.k = k

    def on_epoch_end(self, epoch, logs=None):
        output_tokens = keras_nlp.utils.top_k_search(
            token_logits_fn,
            prompt_tokens,
            max_length=NUM_TOKENS_TO_GENERATE,
            k=self.k,
            from_logits=True,
        )
        txt = tokenizer.detokenize(output_tokens)
        print(f"Top-K search generated text: \n{txt}\n")


text_generation_callback = TopKTextGenerator(k=10)
# Dummy training loop to demonstrate callback.
model.fit(train_ds.take(1), verbose=2, epochs=2, callbacks=[text_generation_callback])

"""
## Conclusion

Congrats, you made it through the example! To recap, in this example, we use KerasNLP
layers to train a sub-word vocabulary, tokenize training data, create a miniature GPT
model, and perform inference with the text generation library.

If you would like to understand how transformers work, or learn more about training the
full GPT model, here are some further readings:
- Attention Is All You Need [Vaswani et al., 2017](https://arxiv.org/pdf/1706.03762.pdf)
- GPT-3 Paper [Brown et al., 2020](https://arxiv.org/pdf/2005.14165.pdf)
"""
