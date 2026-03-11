"""
Fuses the PEFT LoRA adapter into the base model using Hugging Face,
then converts the resulting merged model to a 4-bit MLX model.
"""

import os
import sys
import subprocess
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fuse_and_convert")

BASE_MODEL_ID = "deepseek-ai/deepseek-coder-7b-instruct-v1.5"
ADAPTER_DIR = os.path.join(os.path.dirname(__file__), "models", "patcher")
MERGED_DIR = os.path.join(os.path.dirname(__file__), "models", "patcher_hf_merged")
MLX_DIR = os.path.join(os.path.dirname(__file__), "models", "deepseek_4bit_mlx")

def main():
    if not os.path.exists(ADAPTER_DIR):
        logger.error(f"Adapter not found at {ADAPTER_DIR}")
        sys.exit(1)

    if not os.path.exists(MERGED_DIR):
        logger.info(f"1️⃣ Loading base HF model: {BASE_MODEL_ID}")
        # Load in half-precision on CPU (fits ~14GB RAM on M3)
        base_model = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL_ID,
            torch_dtype=torch.float16,
            device_map="cpu",
            low_cpu_mem_usage=True,
            trust_remote_code=True
        )
        tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_ID, trust_remote_code=True)

        logger.info("2️⃣ Merging PEFT adapter...")
        model = PeftModel.from_pretrained(base_model, ADAPTER_DIR)
        model = model.merge_and_unload()

        logger.info(f"3️⃣ Saving merged HF model to {MERGED_DIR}...")
        model.save_pretrained(MERGED_DIR, safe_serialization=True)
        tokenizer.save_pretrained(MERGED_DIR)
        logger.info("✅ HF model successfully merged and saved.")

        # Free memory before MLX quantization
        del model
        del base_model
        import gc
        gc.collect()

    if not os.path.exists(MLX_DIR):
        logger.info("4️⃣ Converting merged HF model to 4-bit MLX...")
        cmd = [
            "python3", "-m", "mlx_lm.convert",
            "--hf-path", MERGED_DIR,
            "-q", "--q-bits", "4",
            "--mlx-path", MLX_DIR
        ]
        subprocess.run(cmd, check=True)
        logger.info(f"✅ 4-bit MLX model saved to {MLX_DIR}")
        
    logger.info("🎉 All done!")

if __name__ == "__main__":
    main()
