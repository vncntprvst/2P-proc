# Suite2P 
For test and development purposes, you can create a virtual environment for Suite2P.
The fastest way to do this is using [uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd suite2p
uv venv --python 3.9.17 suite2p
```

Activate the virtual environment:

```bash
# Windows:
suite2p\Scripts\activate
# Linux/Mac:
source suite2p/bin/activate
```

Install Suite2P with GUI and IO support, and JupyterLab:

```bash
uv pip install suite2p[gui,io] jupyterlab
```

Start JupyterLab:

```bash
jupyter lab
```

Start Suite2P's GUI:

```bash
suite2p
```
