from server.config import config
from server.core.core import SmartGarage


print("=" * 40)
print("Smart Garage")
print("=" * 40)
print(f"Project : {config['project']['name']}")
print(f"Version : {config['project']['version']}")
print("=" * 40)

garage = SmartGarage()
garage.start()

print("\nSmart Garage ready.")
print("Type 'exit' to quit.\n")

while True:

    prompt = input("You> ")

    if prompt.lower() in ("exit", "quit"):
        break

    response = garage.router.execute(prompt)

    if response:
        print(response)
