FROM wanglabneuro/mesmerize-base:latest

LABEL description="AIND z-motion (axial drift) correction capsule using compute_zcorrel"
LABEL version="1.0"

# Install aind-data-schema and CaImAn (compute_zcorrel loads CaImAn memmaps)
RUN uv pip install aind-data-schema && \
    uv pip install "git+https://github.com/flatironinstitute/CaImAn.git@v1.12.2" && \
    caimanmanager install

# optimouse provides modules.compute_zcorr (the z-correction implementation)
RUN uv pip install optimouse

# Copy capsule code
COPY code/ /code/

WORKDIR /code

# Prebuild Matplotlib font cache
ENV MPLCONFIGDIR=/root/.config/matplotlib
RUN mkdir -p "$MPLCONFIGDIR" && \
    python - <<'PY'
import matplotlib as mpl
mpl.use('Agg')
from matplotlib import font_manager
_ = font_manager.fontManager.ttflist
print('Prebuilt Matplotlib font cache at:', mpl.get_configdir())
PY

# CaImAn environment variables
ENV CAIMAN_DATA=/root/caiman_data
ENV CAIMAN_TEMP=/root/caiman_data/temp

# UTF-8 locale
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=UTF-8 \
    PYTHONUTF8=1

# Test: docker run --rm wanglabneuro/aind_zmotion_correction \
#   python -c "from modules.compute_zcorr import compute_zcorrel; print('ok')"
