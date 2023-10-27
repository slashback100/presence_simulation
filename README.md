*Please :star: this repo if you find it useful*

# Presence Simulation

[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

This Home Assistant component aim to provide a presence simulation in your home while you are away. It will turn on & off lights, switches, covers... based on your history.

# How it works
It will look in the DB for the states history of all the entities configured in the component for a period corresponding to a `delta` variable defined in the component.
It will apply to the entites the same state (and some attributes like brightness and rgb_color) as it was `delta` days ago, in order to simulate your presence.
If the service is running longer than the number of days defined as the `delta`, the component will simply be reset and start over, until the stop service is called.

Supported entities domains:
- `light`
- `cover`
- `media_player`
- All domains for which entities have status `on` or `off` than can be turned on/off with service `homeassistant.turn_on` and `homeassistant.turn_off` (`automation`, `switch`, `group`...).

# Pre-requisit
The `history` integration must be activated - [which it is by default](https://www.home-assistant.io/integrations/history/). The period kept in the DB should be bigger than the delta used in the simulation. The default number of days kept is 10 and this [can be configured](https://www.home-assistant.io/integrations/recorder/) with the `recorder` integration.

# Installation
## Option 1
- In your Home Assistant configuration directory (`~/.homeassistant` for instance), create a directory `custom_components/presence_simulation` and put the code in it.
- Restart Home Assistant
## Option 2
- Go in your Home Assistant configuration directory (`~/.homeassistant` for instance)
- `git clone https://github.com/slashback100/presence_simulation.git`. It will create the directory `custom_components/presence_simulation`
- Restart Home Assistant
## Option 3 (recommended)
- Have [HACS](https://hacs.xyz/) installed, this will allow you to easily manage and track updates.
- You can either search for "Presence Simulation" or use this link [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?repository=presence_simulation&category=Integration&owner=slashback100).
- Click Install below the found integration.
- Restart Home Assistant

NB: it can also be added as a custom repository if you have an issue with above procedure

# Configuration
* In the UI, go in Configuration > Integration (or click here [![Open your Home Assistant instance and show your integrations.](https://my.home-assistant.io/badges/integrations.svg)](https://my.home-assistant.io/redirect/integrations/)) 
* Click on the '+' button
* Search for "Presence Simulation"
* Confirm:

<p align="center">
  <img src="https://github.com/slashback100/presence_simulation/raw/main/custom_components/presence_simulation/images/configFlow.png" alt="accessibility text">
</p>

* Set the group of entities to be used in the simulation. It can be a group of lights, switches, covers, light groups, media_player or of any component that can be turned on and off with the service `homeassistant.turn_on` and `homeassistant.turn_off`. You can also setup several entities, separated with ','
* Set the number of days of history the simulation will use (the delta)
* Set the poll interval in seconds that determines how quickly the simulation notices that it has been requested to stop. Default is 30 seconds. Warning, the smaller the number you choose, the more computing process the component will take.
* After the simulation, choose to restore the states as they were before the start of ths simulation
* You can choose to randomize the activation/deactivation of your entities. '0' to disable this behaviour, or a period in seconds for the maximum of seconds the random switching will be done. This random period is added (or substracted) from the time the entity was actually switched on or off in your historical data.

You can edit these configurations afterwards by clicking on Options in the integration screen.

# Use it

The component will create an entity called `switch.presence_simulation`. This entity will be set to `on` when the simulation is running. `off` otherwise.
You have 2 ways of launching the simulation:
## With the switch
Toggling the `switch.presence_simulation` will toggle the presence simulation.
## With the services
Three services are available:
### Start the simulation
The service `presence_simulation.start` will start the simulation and set the `switch.presence_simulation` entity to `on`.
Optionally, you can reference a list of entities, a delta or choose to restore the states if you want to override the component configuration:
```
entity_id:
  - group.outside_lights
  - light.living_room
  - light.hall
delta: 5
restore_states: True
random: 300
```
### Stop the simulation
The service `presence_simulation.stop` will stop the simulation and set the `switch.presence_simulation` entity to `off`.
### Toggle the simulation
The service `presence_simulation.toggle` will start or stop the simulation, depending on the current state of the `switch.presence_simulation` entity.

# Tutorials
Tristan's Smartes Heim creates a german video how to use it: https://youtu.be/5vCp3iKZb4Q
Smart Home Junkie's English tutorial: https://youtu.be/OTQu3BMr3EU

# Buy me a coffee
Liked some of my work? Buy me a coffee (or more likely a beer)

<a href="https://www.buymeacoffee.com/slashback" target="_blank"><img src="https://bmc-cdn.nyc3.digitaloceanspaces.com/BMC-button-images/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: auto !important;width: auto !important;" ></a>
