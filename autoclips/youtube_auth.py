from .youtube import authorize_locally, channel

if __name__ == "__main__":
    print(authorize_locally())
    print("Canal autorizado:", channel())
