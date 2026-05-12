@REM This file contains commands for running specific tasks 

@REM for linnux virtual env
python -m venv venv
source venv/bin/activate

@REM for windows virtual env
python -m venv venv
.\venv\Scripts\Activate.ps1


pip install -r requirements.txt
python app.py 
python -c "import bcrypt; print(bcrypt.hashpw('YourPasswordHere'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8'))"
