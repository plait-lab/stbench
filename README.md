# stbench

Benchmarking framework for `stsearch` a code search tool with support for partial code queries.

## Setup

```console
$ pip install -r requirements.txt
$ git submodule update --init --recursive
$ tar xf corpus.tgz  # provided separately
```

## Usage

```console
$ python -m stbench -h
```

## Testing

```console
$ python -m stbench \
    --queries queries/javascript/express/security/injection \
    --corpus corpus/sample.in \
    --results results/sample
```

## Reproduce

```console
$ python -m stbench \
    --queries queries/javascript/express \
    --corpus corpus/complete.in \
    --results results/corpus
```
