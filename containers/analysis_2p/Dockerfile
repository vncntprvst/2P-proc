FROM wanglabneuro/mesmerize-base:latest

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
