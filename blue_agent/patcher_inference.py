"""
blue_agent/patcher_inference.py

Loads DeepSeek-Coder-7B base model + merges your Kaggle-trained LoRA adapter.
Uses MLX for fast Apple Silicon inference (3-4x faster than PyTorch on M3 Pro).

First run will convert the base model to 4-bit MLX format (~4GB) and save locally.
Subsequent runs load from the converted MLX format instantly.
"""

import os
import logging
import subprocess

# MLX requires these updated imports instead of Transformers/PEFT
from mlx_lm import load, generate

logger = logging.getLogger("BLUE_AGENT.patcher")

BASE_MODEL_ID = "deepseek-ai/deepseek-coder-7b-instruct-v1.5"
ADAPTER_DIR = os.path.join(os.path.dirname(__file__), "models", "patcher")
MLX_BASE_DIR = os.path.join(os.path.dirname(__file__), "models", "deepseek_4bit_mlx")

# Prompt template — Few-shot examples anchor the model to use spaces and proper formatting
PATCH_PROMPT_TEMPLATE = """### Vulnerability Report
CVE: UNKNOWN
Type: SQL Injection
Severity: CRITICAL
Description: User input directly used in query.

### Vulnerable Code
cursor.execute("SELECT * FROM users WHERE id = " + user_id)

### Task
Generate a secure patch with explanation.

### Secure Patch
```python
# Securely use parameterized queries
cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
```
### Explanation
Use parameterization to prevent SQL injection.

---

### Vulnerability Report
CVE: {cve_id}
Type: {vulnerability_type}
Severity: CRITICAL
Description: {description}

### Vulnerable Code
{vulnerable_code}

### Task
Generate a secure patch with explanation.

### Secure Patch
"""


class PatcherInference:
    """
    Wraps DeepSeek-Coder-7B + LoRA adapter for local patch generation using MLX.
    Runs in 4-bit quantization natively optimized for Apple Silicon.
    """

    def __init__(self):
        self.model = None
        self.tokenizer = None
        self._load()

    def _load(self):
        """
        Load MLX 4-bit model and LoRA adapter.
        """
        if not os.path.exists(ADAPTER_DIR):
            raise FileNotFoundError(
                f"LoRA adapter not found at {ADAPTER_DIR}\n"
                f"Download patcher_final/ from Kaggle and place contents in blue_agent/models/patcher/"
            )

        adapter_config = os.path.join(ADAPTER_DIR, "adapter_config.json")
        if not os.path.exists(adapter_config):
            raise FileNotFoundError(
                f"adapter_config.json not found in {ADAPTER_DIR}\n"
                f"Ensure full patcher_final/ folder contents are present"
            )

        # 1. Convert Base Model to MLX 4-bit if not exists
        if not os.path.exists(MLX_BASE_DIR):
            logger.info(f"⚙️ 4-bit MLX merged model not found. Running fusion and conversion...")
            logger.info("This will take a few minutes but only happens once.")
            
            # Use subprocess to run the setup script
            setup_script = os.path.join(os.path.dirname(__file__), "setup_mlx_patcher.py")
            cmd = ["python3", setup_script]
            try:
                subprocess.run(cmd, check=True)
                logger.info("✅ LoRA adapter successfully fused and converted to MLX 4-bit format.")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to fuse and convert to MLX format: {e}")
                raise

        # 2. Load MLX Model
        logger.info(f"📥 Loading MLX model from {MLX_BASE_DIR}...")
        self.model, self.tokenizer = load(MLX_BASE_DIR)
        
        # MLX tokenizer export corrupts the deepseek vocabulary spacings (treats it as LLaMA).
        # We must load the native AutoTokenizer to decode the raw tokens properly.
        from transformers import AutoTokenizer
        self.hf_tokenizer = AutoTokenizer.from_pretrained("deepseek-ai/deepseek-coder-7b-instruct-v1.5")
        
        logger.info("✅ PatcherAgent loaded and ready with MLX!")

    def generate_patch(
        self,
        vulnerable_code: str,
        vulnerability_type: str,
        description: str = "",
        cve_id: str = "UNKNOWN",
        max_new_tokens: int = 512,
        temperature: float = 0.2,
    ) -> dict:
        """
        Generate a secure patch for the given vulnerable code using MLX.
        """
        if not vulnerable_code or not vulnerable_code.strip():
            return {"patched_code": vulnerable_code, "explanation": "No code provided", "raw_output": ""}

        prompt = PATCH_PROMPT_TEMPLATE.format(
            cve_id=cve_id,
            vulnerability_type=vulnerability_type,
            description=description or f"Detected {vulnerability_type} vulnerability",
            vulnerable_code=vulnerable_code[:2000],  # truncate very long code
        )

        import mlx_lm
        
        try:
            # Generate raw tokens directly to bypass tokenizer bugs with spaces/newlines
            tokens = []
            for t in mlx_lm.stream_generate(
                model=self.model,
                tokenizer=self.tokenizer,
                prompt=prompt,
                max_tokens=max_new_tokens
            ):
                tokens.append(t.token)
            
            # Use pristine huggingface decode
            raw_output = self.hf_tokenizer.decode(tokens, skip_special_tokens=True)
            
            patched_code, explanation = self._parse_output(raw_output, vulnerable_code)

            return {
                "patched_code": patched_code,
                "explanation": explanation,
                "raw_output": raw_output,
            }

        except Exception as e:
            logger.error(f"Patcher inference error: {e}")
            return {
                "patched_code": vulnerable_code,
                "explanation": f"Patch generation failed: {e}",
                "raw_output": "",
            }

    def _parse_output(self, raw_output: str, fallback_code: str) -> tuple:
        """
        Extract generated code from LLM output.
        Strategy: try the lightest-touch extraction first, only apply
        aggressive reconstruction if AST validation fails.
        """
        import re
        import ast

        # 0. BPE-to-Text mapping (always safe)
        raw_output = raw_output.replace("Ġ", " ").replace("Ċ", "\n").replace("ĉ", "\n").replace("č", " ")
        
        explanation = "Patch applied."

        # 1. Try to extract a markdown code block
        match = re.search(r"```(?:python)?\s*\n?(.*?)```", raw_output, re.DOTALL)
        if match:
            candidate = match.group(1).strip()
        else:
            # Fallback: grab text after "### Secure Patch"
            parts = re.split(r"###\s*Secure\s*Patch", raw_output)
            if len(parts) > 1:
                candidate = parts[-1].split("###")[0].strip()
            else:
                candidate = raw_output.strip()

        if len(candidate) < 5:
            candidate = fallback_code

        # 2. Try AST validation on the candidate as-is (lightest touch)
        try:
            ast.parse(candidate)
            return candidate, explanation
        except SyntaxError:
            pass

        # 3. If that failed, try aggressive reconstruction
        patched = candidate
        
        # Keyword spacing
        keywords = ["def", "if", "return", "elif", "import", "from", "class", "with",
                     "as", "and", "or", "not", "is", "try", "except", "finally", "raise"]
        for kw in keywords:
            patched = re.sub(r'\b' + kw + r'([a-zA-Z_])', kw + ' \\1', patched)
            patched = re.sub(r'([\)\]\}\'\"])' + kw + r'\b', r'\1 ' + kw, patched)
        
        # Decorator fix
        patched = re.sub(r'(@\w+\.\w+\([^)]*\))([a-zA-Z_])', r'\1\n\2', patched)
        patched = patched.replace("@ap\np.post", "@app.post")
        
        # Statement boundary newlines
        patched = re.sub(r'([:\)\]\}])\s*([a-zA-Z_])', r'\1\n\2', patched)
        patched = re.sub(r'(\d)\s*([a-zA-Z_])', r'\1\n\2', patched)
        
        # Heuristic indenter
        lines = patched.split('\n')
        out_lines = []
        indent = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            out_lines.append("    " * indent + line)
            if line.endswith(':'):
                indent += 1
            elif line.startswith(('return', 'raise')):
                indent = max(0, indent - 1)
        
        reconstructed = '\n'.join(out_lines)
        
        # 4. Try AST on the reconstructed version
        try:
            ast.parse(reconstructed)
            return reconstructed, explanation
        except SyntaxError:
            pass
        
        # 5. Last resort: return the original code unchanged (fallback)
        return fallback_code, "Patch generation failed syntax validation. Original code preserved."


# Singleton — load once (expensive), reuse across all patch calls
_patcher_instance = None


def get_patcher() -> PatcherInference:
    global _patcher_instance
    if _patcher_instance is None:
        _patcher_instance = PatcherInference()
    return _patcher_instance


def generate_patch(
    vulnerable_code: str,
    vulnerability_type: str,
    description: str = "",
) -> dict:
    """Convenience function for one-line usage."""
    return get_patcher().generate_patch(
        vulnerable_code=vulnerable_code,
        vulnerability_type=vulnerability_type,
        description=description,
    )