User Interface
==============

### Installation
```bash
pip install streamlit python-dotenv
```
If running the pipeline on the cluster, make sure you have the `.env` file in the `/scripts/utils` directory, with the following content:
```
SSH_TRANSFER_NODE=your_transfer_node
SSH_LOGIN_NODE=your_login_node
```
The `SSH_TRANSFER_NODE` and `SSH_LOGIN_NODE` are the `.ssh/config` aliases for the nodes you use to transfer data and login to the cluster, respectively. It can be the same node.

### Run the UI
```bash
cd ui
streamlit run ui_app.py
```