# Presence Simulation
This Home Assistant component aim to provide a presence simulation in your home while you are away. It will turn on & off lights based on your historic.

# How it works
It will look in the DB for the states historic of all the entities configured in the component for a period corresponding the a `delta` variable defined in the component. 
It will apply to the entites the same state as it was `delta` days ago, in order to simulate your presence. 
If the service is running longer than the number of days defined as the `delta`, the component will simply be reset and start over, until the stop service is called.

# Pre-requisit
The `historic` component should be activated, and the period kept in the DB should be bigger than the delta used in the simulation.

# Installation
In your Home Assistant configuration directory (`~/.homeassistant`), create a directory `custom_components/presence_simulation` and put the code in it.

# Configuration
## YAML
You can configure it through your `configuration.yaml` file:
```
presence_simulation:
    delta: 7
    entity_id: 
      - light.hall
      - light.living_room
      - group.outside_lights
```

* `delta` is the number of days of historic that will be used by the simulation. 7 days is the default.
* `entity_id` contains the list of entities that will be used in the simulation. 

## UI
You can also configure the component in the UI.
* In the UI, go in Configuration > Integration
* Click on the '+' button
* Search for "Presence Simulation"
* Confirm:

![Configuration Window](https://github.com/slashback100/presence_simulation/blob/main/images/configFlow.jpg)

* Set the group of entity to be used in the simulation
* Set the number of days of historic the simulation will use (the delta)

# Use it

The component will create an entity called `presence_simulation.running`. This entity will be set to `on` when the entity is running. `off` otherwise.
Three services are available:
## Start the simulation
The service `presence_simulation.start` will start the simulation and set the `presence_simulation.running` entity to `on`.
## Stop the simulation
The service `presence_simulation.stop` will stop the simulation and set the `presence_simulation.running` entity to `off`.
## Toggle the simulation
The service `presence_simulation.toggle` will start or stop the simulation, depending on the current state of the `presence_simulation.running` entity.
