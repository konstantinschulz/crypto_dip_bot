#!/usr/bin/env bash

sudo systemctl daemon-reload
sudo systemctl restart crypto-dip-bot
sudo systemctl enable --now crypto-dip-bot
sudo systemctl status crypto-dip-bot --no-pager