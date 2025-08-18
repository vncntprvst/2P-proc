FROM python:3.10-slim

# Install dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy conversion script
COPY nwb_conversion.py /code/nwb_conversion.py
WORKDIR /code

# Default entrypoint runs NWB conversion script
ENTRYPOINT ["python", "-u", "/code/nwb_conversion.py"]
