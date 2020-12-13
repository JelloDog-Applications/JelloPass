Featurelink = ('https://tinyurl.com/y3hex46c')
Buglink = ('https://tinyurl.com/yy4o4rgc')
version = ('1.0 beta')
from time import sleep
while True:

	session = input("Do you want to add a password type add or type open to open a password or type help :\n")



	if session =="help":
		help_com = input("type About, Bug, or Feature:\n")

		if help_com ==("Feature"):
			print("Click this link to suggest a new feature" + Featurelink )

		if help_com ==("Bug"):
			print("Please go to this link to report a bug " + Buglink )

		if help_com ==("About"):
			print("PASSWORD MANAGER By Cody Wagner v" + version )

	if session =="open":
		pass_open = input("What is the name of the password?:\n")
		f = open(pass_open, "r")
		print(f.read())
		sleep(10)

	if session =="add":
		new_name = input("What is the name of your password?:\n")
		f = open(new_name, "x")
		password = input("Please enter the password:\n")
		f = open(new_name, "w")
		f.write(password)