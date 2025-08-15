FROM python:3.10-slim

# Install dependencies
COPY context/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# Copy code
COPY . /code/
WORKDIR /code

# Default entrypoint runs NWB conversion script
ENTRYPOINT ["python", "-u", "/code/pipeline/nwb_conversion.py"]
