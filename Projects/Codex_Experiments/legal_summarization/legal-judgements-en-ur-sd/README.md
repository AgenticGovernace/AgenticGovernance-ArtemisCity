---
license: mit
task_categories:
- translation
- summarization
- text-generation
language:
- en
- ur
- sd
tags:
- legal
- pakistan
- multi-task
size_categories:
- 10K<n<100K
---

# Pakistani Legal Judgments Corpus (Multi-Task)

This repository contains a specialized multi-task instruction-tuning dataset for Pakistani Legal Documents. It is designed to train AI models for **OCR Correction**, **Legal Translation**, and **Summarization**.

## Dataset Structure

The dataset is divided into **6 configurations** (subsets) that you can load individually:

| Config Name | Task | Source Language | Target Language | Size (approx) |
|---|---|---|---|---|
| `repair` | OCR Correction | Broken English | Clean English | ~2.3k |
| `translation_ur` | Translation | English | Urdu | ~1.3k |
| `translation_sd` | Translation | English | Sindhi | ~1.3k |
| `summary_en` | Summarization | English | English Summary | ~2.3k |
| `summary_ur` | Summarization | Urdu | Urdu Summary | ~1.3k |
| `summary_sd` | Summarization | Sindhi | Sindhi Summary | ~1.3k |

## Usage

```python
from datasets import load_dataset

# Load English -> Urdu Translation Data
ds = load_dataset("amjadali070/legal-judgements-en-ur-sd", "translation_ur")

# Load OCR Repair Data
ds_repair = load_dataset("amjadali070/legal-judgements-en-ur-sd", "repair")
```

## Data Fields

- `instruction`: The prompt/instruction for the model.
- `input`: The source text (e.g., English judgment).
- `output`: The target text (e.g., Urdu translation or Summary).
- `task`: Internal task tag.

## Source
Collected from Pakistani High Court Judgments, processed and aligned by Amjad Ali regarding MS Thesis.
