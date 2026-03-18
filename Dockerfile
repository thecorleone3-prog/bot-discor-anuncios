FROM python:3.11

# Instalar ffmpeg y libs necesarias
RUN apt-get update && apt-get install -y ffmpeg libsodium-dev

# Carpeta de trabajo
WORKDIR /app

# Copiar archivos del proyecto
COPY . .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Ejecutar el bot si
CMD ["python", "bot.py"]