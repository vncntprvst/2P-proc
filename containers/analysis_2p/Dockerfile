FROM wanglabneuro/mesmerize-base:latest

# Install FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
    
RUN mkdir -p /code && \
    mkdir -p /data

# Copy repo files to code directory
COPY . /code/
WORKDIR /code

# Install spin-top package from GitHub
RUN uv pip install git+https://github.com/vncntprvst/2P-proc.git

# Install additional requirements
RUN uv pip install -r requirements.txt && \
    rm requirements.txt

# Prebuild Matplotlib font cache in the image to avoid first-run delays
# Default the config/cache dir inside the image; runtime can override MPLCONFIGDIR
ENV MPLCONFIGDIR=/root/.config/matplotlib
RUN mkdir -p "$MPLCONFIGDIR" && \
    python - <<'PY'
import matplotlib as mpl
mpl.use('Agg')
from matplotlib import font_manager
# Trigger font scan/cache build
_ = font_manager.fontManager.ttflist
print('Prebuilt Matplotlib font cache at:', mpl.get_configdir())
PY

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
# docker run --rm -it wanglabneuro/spin-top:latest python -c "import caiman; print(caiman.__version__); import pipeline; print('spin-top installed')"
