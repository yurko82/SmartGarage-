# Інструкція з навчання кастомної моделі SmartGarage LoRA

Ця інструкція описує швидке донавчання моделі **Qwen 2.5 Coder 1.5B** під українську мову та команди нашого гаража за допомогою безкоштовного **Google Colab (T4 GPU)** за **~12 хвилин**.

---

## Важливі апаратні обмеження системи (Закладено в датасет)
1. **Ворота:** керуються виключно імпульсним реле (`open`, `close`, `toggle`). Фізичного кінцевика / датчика відкриття **немає і не передбачається**.
2. **Газовий аналізатор:** датчика диму / газу **немає і не передбачається**. Модель чесно інформує про це у разі запитань.
3. **Клімат:** активні датчики Xiaomi BLE працюють у підвалі та на 2-му поверсі. 1-й поверх (гараж) очікує встановлення.
4. **Медіа:** проектор HY350MAX, Bluetooth-колонки JBL Clip 5 (гараж) та JX-BT (1-й поверх).
5. **Присутність:** наразі відстежуються пристрої Юрія (Motorola Edge 50 Pro). База відвідувачів на основі BLE перебуває на етапі планування.
6. **Табу:** суворе блокування російської мови та російськомовного контенту.

---

## Покроковий процес навчання

### Крок 1. Генерація датасету на сервері
Датасет уже згенеровано в цій папці (`train.jsonl` та `val.jsonl`). Якщо ви внесете нові фрази, перегенеруйте його командою:
```bash
python3 training/generate_dataset.py
```

### Крок 2. Навчання в Google Colab (Безкоштовний T4 GPU)
1. Відкрийте [Google Colab](https://colab.research.google.com/) та створіть новий блокнот.
2. У меню оберіть: **Змінити тип середовища виконання** $\rightarrow$ **T4 GPU**.
3. Завантажте файл `train.jsonl` у панель файлів Colab (зліва).
4. У першій клітинці встановіть **Unsloth**:
   ```bash
   !pip install "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
   !pip install --no-deps trl peft accelerate bitsandbytes
   ```
5. Скопіюйте та виконайте вміст файлу `training/train_colab.py`.
6. Навчання триватиме близько **10–12 хвилин**. Після завершення скрипт автоматично сквантує модель у формат **GGUF (Q4_K_M)**.
7. Завантажте згенерований файл `smartgarage-qwen1.5b-uk-q4_k_m.gguf` (розмір ~1.1 ГБ) собі на комп'ютер у папку `models/`.

---

### Крок 3. Підключення моделі в Ollama на ASUS X413E

1. Скопіюйте завантажений GGUF файл у контейнер Ollama:
   ```bash
   docker cp models/smartgarage-qwen1.5b-uk-q4_k_m.gguf ollama:/root/.ollama/models/smartgarage.gguf
   ```

2. Створіть Modelfile всередині контейнера:
   ```bash
   docker exec ollama bash -c 'cat << "EOF" > /tmp/Modelfile.smartgarage
   FROM /root/.ollama/models/smartgarage.gguf
   PARAMETER num_ctx 4096
   PARAMETER temperature 0.1
   PARAMETER top_p 0.9
   EOF'
   ```

3. Зареєструйте модель в Ollama:
   ```bash
   docker exec ollama ollama create smartgarage:1.5b -f /tmp/Modelfile.smartgarage
   ```

4. Оновіть назву моделі у файлі `config/config.yaml`:
   ```yaml
   local_llm:
     enabled: true
     provider: ollama
     model: smartgarage:1.5b
     api_base: http://localhost:11434
   ```

Готово! Ваша персональна модель SmartGarage стане основним офлайн-мозком системи.
