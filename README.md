# cuelight-system
An upgrade on the classic Light switch cue light systems, this system will allow you to have flexibilty in where your cue lights are. Older systems would only work if your technician or stagehand was in sight of the string light or lightbulb for their cue. This system Uses MQTT over wifi to be able to mount receivers in scenery or even a wearable.

The first setup was a Raspberry Pi 5 with the 7" DSI display as the transmitter, and the 2 receivers were a windows computer and a Raspberry PI 4B with DSI display. In the future, there will be an option for ESP32 HMI Displays as "lite", more cost effective receiver that will be battery powered.

# ****Features****

**Centralized Control**: A powerful transmitter GUI allows for manual control of up to 8 channels, a full cue list for show automation, and real-time status monitoring.

**Dual Receiver Types:**
  - Full Receiver: Runs on a Raspberry Pi with a 7" touchscreen for a rich visual display.
  - "Lite" Receiver: A compact, battery-powered ESP32 receiver with a character LCD, ideal for portability. (in development)

**Robust Networking:** Designed to run on a dedicated local network using a travel router or professional access points for maximum reliability.

**User-Friendly Setup:** Receivers can be easily configured on-site. The ESP32 receivers use a "captive portal" for simple Wi-Fi setup via a smartphone.

**Persistent Configuration:** Show files and device settings are saved to JSON files, so the system remembers its state between reboots.

**Unified Code:** The main code is an all-in one setup. The Device can be configured as a Transmitter or Receiver simply by changing the device_role.JSON file

**Added Communication:** Classic Cue light systems were a one-way form of comunication. This system adds the ability for a receiver to click to confirm they have seen the "Stand-By" and the transmitter can see the receiver's name on their dashboard as a confirmed "Standing by". 

**Cue List Function:** Added in a cue list for shows that have the same script every time. Each cue allows you to store what channels will be used in that cue, and label the cue so the receivers can see what cue they are waiting for, and gives Stage Managers less switches to worry about.

**Multi-OS use** I have been able to get this to work on Raspberry PI and Windows, giving more options for receivers (I recommend using on a closed network. Some venue firewalled networks have given trouble).


# **What's next**
I will be working on adding an option for an ESP32 HMI Display which will be battery powered so I can mount the receivers inside of set pieces. Potentially even a wearable. 
Once I get the 7-inch ESP32 display working, I'll add in an STL file and parts list for that setup.
