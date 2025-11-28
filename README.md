# 🏫 IoT-Based Classroom Energy Management System

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/Docker-Ready-blue.svg)](https://www.docker.com/)
[![MQTT](https://img.shields.io/badge/MQTT-Mosquitto-orange.svg)](https://mosquitto.org/)
[![InfluxDB](https://img.shields.io/badge/InfluxDB-2.7-blue.svg)](https://www.influxdata.com/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> An intelligent IoT platform that automates classroom lighting and HVAC control to optimize energy consumption in educational institutions, reducing electricity waste through smart sensor integration and adaptive algorithms.

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture](#-architecture)
- [Technology Stack](#-technology-stack)
- [Quick Start](#-quick-start)
- [Project Structure](#-project-structure)
- [Control Algorithms](#-control-algorithms)
- [API Documentation](#-api-documentation)
- [MQTT Topics](#-mqtt-topics)
- [Telegram Bot](#-telegram-bot)
- [Hardware Setup](#-hardware-setup)
- [Screenshots](#-screenshots)
- [Contributing](#-contributing)
- [Team](#-team)
- [License](#-license)

---

## 🌟 Overview

The **IoT-Based Classroom Energy Management System** is a comprehensive solution designed to reduce energy waste in educational facilities by intelligently controlling lighting and air conditioning based on real-time occupancy and environmental conditions.

### Problem Statement

Educational institutions face significant energy waste from:
- Lights left on in empty classrooms
- Air conditioning running without occupancy
- Inefficient manual control of classroom environments
- Lack of real-time energy consumption monitoring

### Solution

Our system provides:
- **Automated Control**: Motion-activated lighting with smart timeout mechanisms
- **Adaptive HVAC**: Temperature-based air conditioning with dynamic threshold learning
- **Real-time Insights**: Live monitoring via Telegram bot dashboard
- **Data-Driven Decisions**: Historical analytics for energy optimization
- **Scalability**: Microservices architecture supporting unlimited classrooms

---

## ✨ Key Features

### 🔌 Automation
- **Motion-Activated Lighting**: Automatically turns lights on/off based on room occupancy
- **Smart HVAC Control**: Temperature-based air conditioning with weekly learning algorithms
- **Configurable Timeouts**: Customizable delays for lamp and AC shutdown

### 📊 Monitoring & Analytics
- **Real-time Dashboard**: Interactive Telegram bot for instant system insights
- **Historical Data**: Time-series storage with daily, weekly, and monthly reports
- **Energy Consumption Tracking**: Estimated energy savings and cost analysis
- **Occupancy Analytics**: Room usage patterns and heat maps

### 🏗️ Architecture
- **Microservices Design**: Independently scalable, fault-tolerant services
- **MQTT Protocol**: Low-latency, publish-subscribe messaging for IoT devices
- **RESTful APIs**: Standardized HTTP interfaces for data access
- **Service Discovery**: Dynamic registration and health monitoring with Consul
- **Containerized Deployment**: Docker-based infrastructure for easy deployment

### 🔔 Alerting
- **Temperature Alerts**: Notifications when thresholds are exceeded
- **Energy Anomalies**: Warnings for unusual consumption patterns
- **Device Status**: Real-time alerts for offline sensors or actuators

---

## 🏛️ Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     Classroom Environment                        │
│  ┌──────────┐  ┌──────────┐  ┌──────┐  ┌──────────────┐        │
│  │ Motion   │  │Temperature│ │ Lamp │  │      AC      │        │
│  │ Sensor   │  │  Sensor   │ │      │  │              │        │
│  └─────┬────┘  └─────┬─────┘ └───▲──┘  └──────▲───────┘        │
└────────┼─────────────┼───────────┼─────────────┼────────────────┘
         │             │           │             │
         └─────────────▼───────────┼─────────────┼────────┐
              Device Connector     │             │        │
              (Raspberry Pi)       │             │        │
                     │             │             │        │
         ┌───────────▼─────────────┴─────────────┴────────┤
         │              MQTT Broker (Mosquitto)           │
         └───┬───────────────────────────────────┬────────┘
             │                                   │
   ┌─────────▼──────┐                  ┌────────▼─────────┐
   │  DB Adaptor    │                  │  Control Module  │
   │   (Storage)    │                  │ (Business Logic) │
   └────────┬───────┘                  └──────────────────┘
            │                                   
   ┌────────▼───────┐
   │   InfluxDB     │
   │ (Time-Series)  │
   └────────┬───────┘
            │
   ┌────────▼────────────┐       ┌─────────────────┐
   │ Statistics Service  │◄──────┤ Classroom       │
   │   (Analytics)       │       │ Catalog         │
   └─────────┬───────────┘       └─────────────────┘
             │
   ┌─────────▼───────────┐       ┌─────────────────┐
   │  Telegram Bot       │       │ Service Registry│
   │   (Dashboard)       │       │    (Consul)     │
   └─────────────────────┘       └─────────────────┘
```

### Microservices

| Service | Port | Description |
|---------|------|-------------|
| **Device Connector** | - | Publishes sensor data from Raspberry Pi to MQTT |
| **MQTT Broker** | 1883 | Mosquitto message broker for pub/sub messaging |
| **Control Module** | - | Implements control algorithms for lamp/AC |
| **DB Adaptor** | 5002 | Stores sensor data in InfluxDB |
| **Statistics Service** | 5003 | Processes and aggregates energy data |
| **Classroom Catalog** | 5001 | Manages classroom and device metadata |
| **Service Registry** | 8500 | Consul for service discovery and health checks |
| **Telegram Bot** | - | Interactive dashboard for monitoring and alerts |
| **InfluxDB** | 8086 | Time-series database for sensor data |

For detailed architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 🛠️ Technology Stack

### Core Technologies
- **Python 3.9+** - Primary programming language
- **MQTT (Mosquitto)** - Message broker for IoT communication
- **InfluxDB 2.7** - Time-series database
- **Flask** - RESTful API framework
- **Docker & Docker Compose** - Containerization and orchestration

### IoT & Hardware
- **Raspberry Pi** - Edge computing for sensors and actuators
- **PIR Motion Sensor** - Occupancy detection
- **DHT22 Temperature Sensor** - Environmental monitoring
- **Relay Module** - Lamp control
- **IR Transmitter** - Air conditioner control

### Service Infrastructure
- **HashiCorp Consul** - Service registry and discovery
- **python-telegram-bot** - Telegram integration
- **paho-mqtt** - MQTT client library

---

## 🚀 Quick Start

### Prerequisites

- **Docker** and **Docker Compose** installed ([Get Docker](https://docs.docker.com/get-docker/))
- **Python 3.9+** (for local development)
- **Telegram Bot Token** (optional, from [@BotFather](https://t.me/botfather))
- **Raspberry Pi** (optional, for physical sensors)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/iot-classroom-energy-management.git
   cd iot-classroom-energy-management
   ```

2. **Configure environment variables**
   ```bash
   # Create .env file (optional for Telegram bot)
   echo "TELEGRAM_BOT_TOKEN=your_bot_token_here" > .env
   ```

3. **Start all services**
   ```bash
   docker-compose up -d
   ```

4. **Verify services are running**
   ```bash
   docker-compose ps
   ```

5. **Access web interfaces**
   - **InfluxDB UI**: http://localhost:8086 (admin/adminpassword)
   - **Consul UI**: http://localhost:8500
   - **API Endpoints**: http://localhost:5001-5003

### Testing the System

```bash
# Check service health
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:5003/health

# View classrooms
curl http://localhost:5001/api/classrooms

# Get energy statistics
curl "http://localhost:5003/api/statistics/energy-summary?classroom=room1&period=day"
```

For detailed setup instructions, see [GETTING_STARTED.md](GETTING_STARTED.md).

---

## 📁 Project Structure

```
IOT Main/
├── 📄 docker-compose.yml          # Docker orchestration
├── 📄 requirements.txt            # Python dependencies
├── 📄 README.md                   # This file
├── 📄 ARCHITECTURE.md             # System architecture details
├── 📄 API_DOCUMENTATION.md        # REST API reference
├── 📄 GETTING_STARTED.md          # Setup guide
├── 📄 LICENSE                     # MIT License
│
├── 📁 device-connector/           # Raspberry Pi sensor publisher
│   ├── sensor_publisher.py
│   └── requirements.txt
│
├── 📁 control-module/             # Business logic for automation
│   ├── control_service.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── 📁 db-adaptor/                 # Database integration
│   ├── db_service.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── 📁 statistics-service/         # Data analytics
│   ├── statistics_service.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── 📁 classroom-catalog/          # Metadata management
│   ├── catalog_service.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── 📁 telegram-dashboard/         # User interface
│   ├── telegram_bot.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── 📁 service-registry/           # Service discovery
│   ├── registry_client.py
│   └── requirements.txt
│
├── 📁 actuators/                  # Hardware controllers
│   ├── lamp_controller.py
│   ├── ac_controller.py
│   └── requirements.txt
│
└── 📁 docker/                     # Docker configurations
    └── mosquitto/
        └── config/
            └── mosquitto.conf
```

---

## 🧠 Control Algorithms

### Lamp Control Algorithm

```python
if motion_detected:
    turn_lamp_on()
    reset_timeout_timer()
else:
    if timeout_exceeded(5_minutes):
        turn_lamp_off()
```

**Logic:**
- Turn **ON** immediately when motion is detected
- Turn **OFF** after 5 minutes of no motion (configurable)
- Reset timer on any new motion event

### Air Conditioner Control Algorithm

```python
if classroom_occupied:
    threshold = calculate_weekly_average_temp() + offset
    if current_temp > threshold:
        turn_ac_on(comfort_temperature=22°C)
    else:
        turn_ac_off()
else:
    turn_ac_off()
```

**Logic:**
- **Dynamic Threshold**: Calculates weekly average temperature to adapt to seasonal changes
- **Occupied Mode**: Activates AC when temperature exceeds threshold
- **Unoccupied Mode**: Immediately turns off AC to save energy
- **Comfort Temperature**: Default set to 22°C (configurable)

---

## 📡 API Documentation

### Classroom Catalog API (Port 5001)

```bash
# Get all classrooms
GET /api/classrooms

# Get specific classroom
GET /api/classrooms/{id}

# Create new classroom
POST /api/classrooms
Content-Type: application/json
{
  "id": "room3",
  "name": "Classroom 103",
  "building": "Science Building",
  "floor": 2,
  "capacity": 25
}
```

### Statistics Service API (Port 5003)

```bash
# Get daily statistics
GET /api/statistics/daily?classroom=room1&date=2025-11-28

# Get weekly statistics
GET /api/statistics/weekly?classroom=room1&week=2025-W48

# Get monthly statistics
GET /api/statistics/monthly?classroom=room1&month=2025-11

# Get energy summary
GET /api/statistics/energy-summary?classroom=room1&period=week
```

### DB Adaptor API (Port 5002)

```bash
# Query sensor data
GET /api/sensor-data?classroom=room1&sensor_type=temperature&start=2025-11-01T00:00:00Z&end=2025-11-28T23:59:59Z
```

For complete API reference, see [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

---

## 📨 MQTT Topics

### Sensor Data (Published by Device Connector)

```
Topic: {classroom_id}/motion
Payload: {"classroom_id": "room1", "sensor_type": "motion", "value": 1, "timestamp": "2025-11-28T10:30:00Z"}

Topic: {classroom_id}/temperature
Payload: {"classroom_id": "room1", "sensor_type": "temperature", "value": 24.5, "unit": "celsius", "timestamp": "2025-11-28T10:30:00Z"}
```

### Control Commands (Published by Control Module)

```
Topic: {classroom_id}/lamp/control
Payload: {"classroom_id": "room1", "device": "lamp", "command": "ON", "timestamp": "2025-11-28T10:30:00Z"}

Topic: {classroom_id}/ac/control
Payload: {"classroom_id": "room1", "device": "air_conditioner", "command": "ON", "target_temperature": 22, "timestamp": "2025-11-28T10:30:00Z"}
```

### Alerts

```
Topic: alerts/temperature
Payload: {"classroom_id": "room1", "alert_type": "temperature", "message": "High temperature: 28°C", "timestamp": "2025-11-28T10:30:00Z"}

Topic: alerts/energy
Payload: {"classroom_id": "room1", "alert_type": "energy", "message": "High energy consumption detected", "timestamp": "2025-11-28T10:30:00Z"}
```

---

## 💬 Telegram Bot

### Setup

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Copy the bot token
3. Add to `.env` file: `TELEGRAM_BOT_TOKEN=your_token`
4. Restart the telegram-dashboard service

### Bot Commands

- `/start` - Initialize the bot
- `/stats` - Get real-time statistics for all classrooms
- `/daily` - View daily energy report
- `/weekly` - View weekly energy report
- `/monthly` - View monthly energy report
- `/classrooms` - List all registered classrooms
- `/help` - Show available commands

### Features

- ✅ Real-time energy consumption monitoring
- ✅ Automatic threshold alerts
- ✅ Historical data visualization
- ✅ Multi-classroom support
- ✅ Interactive command interface

---

## 🔧 Hardware Setup

### Required Components

#### For Device Connector (Raspberry Pi)
- Raspberry Pi 3/4 (or similar)
- PIR Motion Sensor (HC-SR501)
- DHT22 Temperature/Humidity Sensor
- Breadboard and jumper wires
- Power supply

#### For Actuators (Raspberry Pi)
- Raspberry Pi 3/4 (or similar)
- Relay Module (for lamp control)
- IR Transmitter (for AC control)
- Power supply

### Wiring Diagram

```
Raspberry Pi GPIO:
├── PIR Sensor (VCC → 5V, GND → GND, OUT → GPIO17)
├── DHT22 Sensor (VCC → 3.3V, GND → GND, DATA → GPIO4)
├── Relay Module (VCC → 5V, GND → GND, IN → GPIO18)
└── IR Transmitter (VCC → 3.3V, GND → GND, DATA → GPIO23)
```

### Running on Raspberry Pi

```bash
# On your Raspberry Pi
cd device-connector
python sensor_publisher.py

# In separate terminals for actuators
cd actuators
python lamp_controller.py
python ac_controller.py
```

---

## 📸 Screenshots

* screenshots of Telegram bot, InfluxDB dashboard, and system monitoring will be added here*

---

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guide for Python code
- Add unit tests for new features
- Update documentation as needed
- Ensure Docker builds succeed

---

## 👥 Team

This project was developed by:

- **Ehsan Nikpey**
- **Shabnam Amouie**
- **Alireza Nourishad**
- **Seyed Erfan Ghoreishi** 

**Version:** 1.3  
**Date:** November 18, 2025

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🌐 Additional Resources

- [Architecture Documentation](ARCHITECTURE.md) - Detailed system design
- [API Documentation](API_DOCUMENTATION.md) - Complete API reference
- [Getting Started Guide](GETTING_STARTED.md) - Step-by-step setup
- [MQTT Protocol](https://mqtt.org/) - Learn about MQTT
- [InfluxDB Documentation](https://docs.influxdata.com/) - Time-series database

---

## 📧 Contact

For questions, suggestions, or support:
- Open an issue on GitHub
- Contact the development team

---

<div align="center">

**⭐ Star this repository if you find it helpful! ⭐**

Made with ❤️ for sustainable education

</div>

