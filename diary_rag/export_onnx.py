"""One-shot export: BGE-small-zh-v1.5 BERT backbone → ONNX + tokenizer.

Run once with current torch/transformers installed.  After exporting, the
ONNX model + tokenizer serve as the runtime — torch/transformers are no
longer needed in production.

Output directory: diary_rag/data/bge-zh/
  - model.onnx       BERT backbone (hidden_size=512, 4 layers)
  - tokenizer.json   HF fast tokenizer (includes BERT post-processing template)
"""

from __future__ import annotations

import os
import sys

# Enforce UTF-8 for stdout/stderr — torch.onnx prints emoji that
# crashes the legacy GBK console on Chinese Windows.
if sys.stdout.encoding != "utf-8":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
import shutil
import sys
from pathlib import Path

import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = Path(__file__).parent / "data"
OUT_DIR = DATA_DIR / "bge-zh"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def export_onnx() -> None:
    """Load BERT from sentence_transformers, export to ONNX."""
    from sentence_transformers import SentenceTransformer

    print("Loading BGE-small-zh-v1.5 from HuggingFace cache...")
    st_model = SentenceTransformer("BAAI/bge-small-zh-v1.5", local_files_only=True)
    bert = st_model._modules["0"].auto_model  # HuggingFace BertModel
    bert.eval()

    # Verify hidden_size matches config
    hidden_size = bert.config.hidden_size
    assert hidden_size == 512, f"Expected hidden_size=512, got {hidden_size}"

    class BertBackbone(torch.nn.Module):
        """Wrap BertModel to expose only last_hidden_state for ONNX export."""

        def __init__(self, bert_model):
            super().__init__()
            self.bert = bert_model

        def forward(self, input_ids, attention_mask, token_type_ids):
            out = self.bert(
                input_ids=input_ids,
                attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            )
            return out.last_hidden_state

    wrapper = BertBackbone(bert).eval()

    # Use batch_size=2 dummy so ONNX doesn't fold batch dim to 1.
    # do_constant_folding=False prevents internal MatMul dims from being hardcoded.
    batch_size, seq_len = 2, 64
    dummy_ids = torch.randint(0, bert.config.vocab_size, (batch_size, seq_len))
    dummy_mask = torch.ones(batch_size, seq_len, dtype=torch.long)
    dummy_type = torch.zeros(batch_size, seq_len, dtype=torch.long)

    out_path = OUT_DIR / "model.onnx"
    print(f"Exporting ONNX to {out_path}...")
    torch.onnx.export(
        wrapper,
        (dummy_ids, dummy_mask, dummy_type),
        str(out_path),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["last_hidden_state"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq_len"},
            "attention_mask": {0: "batch", 1: "seq_len"},
            "token_type_ids": {0: "batch", 1: "seq_len"},
            "last_hidden_state": {0: "batch", 1: "seq_len"},
        },
        opset_version=14,
        do_constant_folding=False,
        dynamo=False,
    )
    print(f"  ONNX model: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")


def copy_tokenizer() -> None:
    """Copy tokenizer files from HuggingFace cache."""
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = hf_cache / "models--BAAI--bge-small-zh-v1.5"
    snapshot = sorted(model_dir.glob("snapshots/*"))[0]

    src = snapshot / "tokenizer.json"
    dst = OUT_DIR / "tokenizer.json"
    shutil.copy2(src, dst)
    print(f"  tokenizer: {dst} ({dst.stat().st_size / 1024:.1f} KB)")


def main() -> None:
    print("=== BGE-small-zh-v1.5 → ONNX export ===")
    export_onnx()
    copy_tokenizer()
    print("Done. Runtime files in", OUT_DIR)
    print()
    print("Server now only needs: onnxruntime, tokenizers (no torch!)")


if __name__ == "__main__":
    main()
