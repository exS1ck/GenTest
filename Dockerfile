FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    build-essential \
    gfortran \
    libgsl-dev \
    libopenblas-dev \
    r-base \
    git \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем PLINK
RUN wget https://s3.amazonaws.com/plink1-assets/plink_linux_x86_64_20231211.zip && \
    unzip plink_linux_x86_64_20231211.zip && \
    mv plink /usr/local/bin/ && \
    chmod +x /usr/local/bin/plink && \
    rm plink_linux_x86_64_20231211.zip

# Клонируем и компилируем AdmixTools
RUN git clone https://github.com/DReichLab/AdmixTools.git /AdmixTools && \
    cd /AdmixTools/src && \
    make clobber && \
    make all && \
    make install

# Создаём рабочую директорию
WORKDIR /app

# Копируем requirements.txt и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем все файлы приложения
COPY . .

# Создаём директорию для временных файлов
RUN mkdir -p /tmp/plink_data

# Команда запуска
CMD ["python", "bot.py"]