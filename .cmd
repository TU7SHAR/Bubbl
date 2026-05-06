@REM This file contains commands for running specific tasks 

pip install -r requirements.txt
python app.py 
python -c "import bcrypt; print(bcrypt.hashpw('YourPasswordHere'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'))"
