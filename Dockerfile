# --- အဆင့် ၁: Base Image ---
FROM python:3.11-slim

# --- အဆင့် ၂: System Dependencies များကို သွင်းခြင်း ---
RUN apt-get update && apt-get install -y \
    build-essential \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# --- အဆင့် ၃: Working Directory သတ်မှတ်ခြင်း ---
WORKDIR /app

# --- အဆင့် ၄: Font များကို Copy ကူးခြင်း (Chart အတွက်) ---
# Python script က /app/fonts/ ထဲမှာ Font ကို ရှာမှာ ဖြစ်တဲ့အတွက်၊
# /app folder အောက်ကို တိုက်ရိုက် ကူးထည့်ပါမယ်။
COPY fonts/ /app/fonts/

# --- အဆင့် ၅: Python Library များကို သွင်းခြင်း ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- အဆင့် ၆: Bot Code များကို Copy ကူးခြင်း ---
COPY adupaymentrockvs.py .
COPY models.py .
COPY database_manager.py .

# --- အဆင့် ၇: Bot ကို Run ခြင်း ---
CMD ["python", "adupaymentrockvs.py"]