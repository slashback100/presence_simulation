# Presence Simulation
This Home Assistant component aim to provide a presence simulation in your home while you are away. It will turn on & off lights, switches, ... based on your historic.

# How it works
It will look in the DB for the states historic of all the entities configured in the component for a period corresponding the a `delta` variable defined in the component.
It will apply to the entites the same state (and some attributes like brightness and rgb_color) as it was `delta` days ago, in order to simulate your presence.
If the service is running longer than the number of days defined as the `delta`, the component will simply be reset and start over, until the stop service is called.

# Pre-requisit
The `historic` component should be activated, and the period kept in the DB should be bigger than the delta used in the simulation.

# Installation
## Option 1
- In your Home Assistant configuration directory (`~/.homeassistant`), create a directory `custom_components/presence_simulation` and put the code in it.
- Restart Home Assistant
## Option 2
- In your Home Assistant configuration directory (`~/.homeassistant`), create a directory `custom_components` if not already existing and navigate in it.
- `git clone https://github.com/slashback100/presence_simulation.git`
- Restart Home Assistant
# Configuration
* In the UI, go in Configuration > Integration
* Click on the '+' button
* Search for "Presence Simulation"
* Confirm:

<p align="center">
  <img src="/images/configFlow..png" width="400" alt="accessibility text">
</p>

* Set the group of entity to be used in the simulation. It can be a group of lights, switches or of any component that can be turned on and off with the service `homeassistant.turn_on` and `homeassistant.turn_off`
* Set the number of days of historic the simulation will use (the delta)
* Set the number of scan interval used to switch entities in seconds. Default is 30 seconds. Warning, the smallest number you choose, the more computing process the component will take.

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
Optionally, you can reference a delta or list of entities if you want to overridde the component configuration:
```
entity_id:
  - group.outside_lights
  - light.living_room
  - light.hall
delta: 5
```
### Stop the simulation
The service `presence_simulation.stop` will stop the simulation and set the `switch.presence_simulation` entity to `off`.
### Toggle the simulation
The service `presence_simulation.toggle` will start or stop the simulation, depending on the current state of the `switch.presence_simulation` entity.
