import torch
import torch.nn as nn
import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models", "detector")
MODEL_PATH = os.path.join(MODEL_DIR, "best_model.pt")

LABELS = [
    "sql_injection", "integer_overflow", "negative_quantity",
    "privilege_escalation", "path_traversal", "clean"
]

@dataclass
class DetectorConfig:
    model_name: str = "microsoft/codebert-base"
    num_labels: int = 6
    hidden_size: int = 768
    dropout: float = 0.1
    max_length: int = 512

class DetectorModel(nn.Module):
    def __init__(self, cfg: DetectorConfig):
        super().__init__()
        from transformers import RobertaModel
        self.encoder = RobertaModel.from_pretrained(cfg.model_name)
        self.dropout = nn.Dropout(cfg.dropout)
        self.classifier = nn.Linear(cfg.hidden_size, cfg.num_labels)

    def forward(self, input_ids, attention_mask):
        out = self.encoder(input_ids=input_ids, attention_mask=attention_mask)
        pooled = out.last_hidden_state[:, 0, :]
        return self.classifier(self.dropout(pooled))


class DetectorInference:
    def __init__(self):
        self.device = (
            torch.device("mps") if torch.backends.mps.is_available()
            else torch.device("cuda") if torch.cuda.is_available()
            else torch.device("cpu")
        )
        logger.info(f"Detector using device: {self.device}")
        self._load()

    def _load(self):
        import __main__
        __main__.DetectorConfig = DetectorConfig

        checkpoint = torch.load(MODEL_PATH, map_location=self.device, weights_only=False)

        cfg = checkpoint.get("cfg", DetectorConfig())
        if not isinstance(cfg, DetectorConfig):
            cfg = DetectorConfig()

        self.label_names = checkpoint.get("label_names", LABELS)
        self.model = DetectorModel(cfg).to(self.device)
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()

        from transformers import RobertaTokenizer
        self.tokenizer = RobertaTokenizer.from_pretrained("microsoft/codebert-base")
        logger.info(f"Detector loaded — epoch {checkpoint.get('epoch')}, val_f1={checkpoint.get('val_f1', 'N/A')}")

    def classify(self, code: str) -> dict:
        enc = self.tokenizer(
            code,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding="max_length",
        )
        input_ids = enc["input_ids"].to(self.device)
        attention_mask = enc["attention_mask"].to(self.device)

        with torch.no_grad():
            logits = self.model(input_ids, attention_mask)
            probs = torch.softmax(logits, dim=-1)[0]
            pred_idx = probs.argmax().item()

        label = self.label_names[pred_idx] if pred_idx < len(self.label_names) else f"class_{pred_idx}"
        confidence = probs[pred_idx].item()

        return {
            "label": label,
            "confidence": round(confidence, 4),
            "is_vulnerable": label != "clean",
            "all_scores": {
                self.label_names[i]: round(probs[i].item(), 4)
                for i in range(len(self.label_names))
            }
        }


_detector_instance: Optional[DetectorInference] = None

def get_detector() -> DetectorInference:
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = DetectorInference()
    return _detector_instance

def classify_code(code: str) -> dict:
    return get_detector().classify(code)