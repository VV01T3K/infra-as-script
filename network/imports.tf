# One-time adoption of what already exists on the router (IDs read from it on 2026-10-04).
# Zones and policies are imported as "<site>:<id>".
# After the first apply these are recorded in the state; the blocks can then be deleted.

import {
  to = unifi_network.lan["management"]
  id = "6ab7f1f8123c36cb9d21f73d"
}

import {
  to = unifi_network.lan["personal"]
  id = "6ab8889a04823f733dfb68e3"
}

import {
  to = unifi_network.lan["infra"]
  id = "6ab88b7704823f733dfb69e3"
}

import {
  to = unifi_firewall_zone.infra
  id = "default:6ab88b7c04823f733dfb69e9"
}

import {
  to = unifi_firewall_zone_policy.internal_to_infra
  id = "default:6ab88b9104823f733dfb6a10"
}

import {
  to = unifi_firewall_zone_policy.komoda_to_proxmox_ui
  id = "default:6abbd6bce0aefae407165703"
}

import {
  to = unifi_device.flex_mini
  id = "58:d6:1f:5a:44:69"
}

import {
  to = unifi_device.gateway
  id = "74:fa:29:55:44:53"
}

import {
  to = unifi_user.proxmox
  id = "6ab8785504823f733dfb6762"
}

import {
  to = unifi_user.archer
  id = "6ab87b8004823f733dfb67b3"
}
