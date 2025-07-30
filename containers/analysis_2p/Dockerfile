FROM wanglabneuro/mesmerize-base:0.2.0
# FROM wanglabneuro/mesmerize-base:latest

RUN mkdir -p /code && \
    mkdir -p /data

# Set working directory to Mesmerize code directory
COPY Mesmerize /code/Mesmerize
COPY requirements.txt /code/Mesmerize/requirements.txt
WORKDIR /code/Mesmerize

RUN pip install -r requirements.txt && \
    rm requirements.txt

# Set CAIMAN_DATA environment variable
ENV CAIMAN_DATA=/root/caiman_data
# Set $CAIMAN_TEMP
ENV CAIMAN_TEMP=/root/caiman_data/temp
