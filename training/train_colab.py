# ==============================================================================
# Smart Garage - Unsloth LoRA Fine-Tuning Script for Google Colab (Free T4 GPU)
# Target Model: Qwen 2.5 Coder 1.5B Instruct -> SmartGarage UK GGUF
# ==============================================================================

# 1. Install Unsloth and required packages (Run in Colab cell)
# !pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
# !pip install --no-deps trl peft accelerate bitsandbytes

import json
import torch
from datasets import Dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

# 2. Configuration
max_seq_length = 2048
dtype = None  # None for auto detection (Float16 or Bfloat16)
load_in_4bit = True  # 4bit quantization to fit easily within 4GB VRAM
model_name = "unsloth/Qwen2.5-Coder-1.5B-Instruct"

print("==> Завантаження базової моделі:", model_name)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_name,
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=load_in_4bit,
)

# 3. Add LoRA Adapters
print("==> Налаштування LoRA адаптерів...")
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=32,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
    use_rslora=False,
    loftq_config=None,
)

# 4. Load Dataset
print("==> Завантаження датасету train.jsonl...")
records = []
with open("train.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

# Format to ChatML strings
formatted_texts = []
for r in records:
    text = tokenizer.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=False)
    formatted_texts.append(text)

dataset = Dataset.from_dict({"text": formatted_texts})
print(f"==> Підготовлено {len(dataset)} прикладів для навчання.")

# 5. Training
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=4,
        gradient_accumulation_steps=2,
        warmup_steps=10,
        num_train_epochs=3,
        learning_rate=2e-4,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=5,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=42,
        output_dir="outputs",
    ),
)

print("==> Старт тренування...")
trainer_stats = trainer.train()
print("==> Тренування успішно завершено!")

# 6. Export directly to GGUF (q4_k_m) for Ollama
print("==> Експорт моделі у формат GGUF (q4_k_m)...")
model.save_pretrained_gguf(
    "smartgarage-qwen1.5b-uk",
    tokenizer,
    quantization_method="q4_k_m"
)

print("==> ГОТОВО! Файл 'smartgarage-qwen1.5b-uk-q4_k_m.gguf' готовий до завантаження.")
