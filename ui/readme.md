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
### Run the UI
```bash
cd ui
streamlit run ui_app.py
```