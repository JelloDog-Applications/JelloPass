answer = input("Do you want to open or create a password?:\n")

if answer =="open":
    code = input("Please enter the name of your password:\n")
    f = open(code, "r")
    print(f.read())

elif answer == "create":
    global password
    name = input("Please enter a name for your password:\n")
    f = open(name, "x")
    password = input("Please enter the password:\n")
#    encrypt_message(password)

