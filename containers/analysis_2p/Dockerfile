FROM wanglabneuro/mesmerize-base:latest

# Install FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
    
RUN mkdir -p /code && \
    mkdir -p /data

# Copy repo files to code directory
COPY . /code/
WORKDIR /code

RUN uv pip install -r requirements.txt && \
    rm requirements.txt

# Set CAIMAN_DATA environment variable
ENV CAIMAN_DATA=/root/caiman_data
# Set $CAIMAN_TEMP
ENV CAIMAN_TEMP=/root/caiman_data/temp
# Set UTF-8 environment variables
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUTF8=1

# Test if the container is working: 
# docker run --rm -it wanglabneuro/analysis-2p:latest python -c "import caiman; print(caiman.__version__)"