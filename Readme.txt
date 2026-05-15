How to set up:

Install python packages psutil and requests
Install system packages smartmontools and vcgencmd
Allow passwordless execution of smartmontools as root or run as root (not recommended)
If you want to use the connectivity watchdog also allow execution of systemctl reboot

Configure config/configuration.py
Edit config/credentials.py.template as explained in the file

Edit pi-logger.service and follow instructions in the file
