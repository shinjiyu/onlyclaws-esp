workspace "OnlyClaws ESP" "Agent/device framework: cloud control plane + ESP32 Lua runtime. Products = capability plugin subsets (panel, RoArm, …). ADL same gates as mcp_guard." {

    !identifiers hierarchical
    !adrs decisions

    model {
        operator = person "Operator / Agent" "Uses oct_ token; invokes tools; deploys Lua"
        owner = person "Device owner" "kuroneko login; registers devices; mints agent tokens"

        cloudHost = softwareSystem "onlyclaws.world" "Hosted control plane (same codebase as server/)" {
            tags "External" "Env"
        }
        waveshareArm = softwareSystem "Waveshare RoArm servos" "STS/SCS bus on driver board" {
            tags "External" "Env"
        }
        claudeDesktop = softwareSystem "Claude desktop (Hardware Buddy)" "Claude Cowork / Claude Code desktop; BLE Nordic UART, newline JSON; developer mode" {
            tags "External" "Env"
            properties {
                "adl" "decisions/0005-claude-buddy-ble.md"
            }
        }
        visionHost = softwareSystem "OnlyClaws Vision pathway" "Host frame→objects+empties (vision/); not ESP" {
            tags "External" "Env"
            properties {
                "adl" "VISION-PATHWAY.md"
                "path" "vision/"
            }
        }
        jevServoHost = softwareSystem "OnlyClaws JEV servo pathway" "Host slow JEV per-joint intervals → one cloud goal; not ESP" {
            tags "External" "Env"
            properties {
                "adl" "JEV-SERVO-PATHWAY.md; PRESENCE-FOLLOW-PATHWAY.md"
                "path" "jev_servo/"
            }
        }

        onlyclaws = softwareSystem "OnlyClaws ESP" "Multi-tenant device framework + product firmwares" {

            group "L2 — composition" {
                controlPlane = container "Control plane" "FastAPI: register, invoke, scripts, push, events" "Python server/app.py" {
                    tags "Compose"
                    properties {
                        "path" "server/app.py"
                        "role" "compose"
                        "horizon.intention" "Queue messages; tenancy; filter tools by capabilities"
                    }
                }

                deviceRuntime = container "Device runtime" "Wi-Fi, poll pending, wire invoke/script, product wiring" "C++ rlcd/src/main.cpp" {
                    tags "Compose"
                    properties {
                        "path" "rlcd/src/main.cpp"
                        "role" "compose"
                        "horizon.intention" "Orchestrate cloud wire + script engine + selected plugins"
                        "as-is.debt" "Monolithic register of gfx/audio/ble — target PLUGIN-RUNTIME"
                    }
                }

                scriptEngine = container "Script engine" "Lua VM; registers only compiled capability modules" "C++" {
                    tags "Compose"
                    properties {
                        "path" "rlcd/src/script_engine.cpp"
                        "role" "compose"
                        "horizon.intention" "Host on_start/on_loop; no product business rules"
                    }
                }
            }

            group "L2 — contracts" {
                contracts = container "Contracts" "Capability ports: PanelDisplay, InvokeTool, ArmDriver, ScriptHost hooks, device wire DTOs" "C++ headers" {
                    tags "Contracts"
                    properties {
                        "path" "rlcd/include/panel_display.h (+ planned capability.h)"
                        "role" "contracts"
                        "horizon.intention" "Stable ports; slow-growing |C|"
                    }
                }
            }

            group "L2 — plugins (out-degree O(1))" {
                panelPlugin = container "Panel plugin" "RLCD / ePaper PanelDisplay backends" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/include/panel_display.h + st7305 / epd397"
                        "role" "plugin"
                        "horizon.intention" "1bpp draw + flush; compile-time W×H"
                        "horizon.deps" "contracts"
                    }
                }

                audioPlugin = container "Audio plugin" "ES8311 beep / PCM" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/src/audio_es8311.cpp"
                        "role" "plugin"
                        "horizon.deps" "contracts"
                    }
                }

                blePadPlugin = container "BLE/Pad plugin" "NimBLE D-pad + Nordic UART transport + LAN HTTP pad" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/src/ble_ctrl.cpp + http_pad + pad_ctrl"
                        "role" "plugin"
                        "horizon.deps" "contracts + wifi_nvs"
                    }
                }

                claudeBuddyPlugin = container "Claude Buddy plugin" "Hardware Buddy protocol: session state, permission prompt card, Lua claude.*" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/src/claude_buddy.cpp + claude_proto.cpp"
                        "role" "plugin"
                        "horizon.intention" "Show Claude sessions; approve/deny tool calls on device buttons"
                        "horizon.deps" "contracts"
                        "adl" "decisions/0005-claude-buddy-ble.md"
                    }
                }

                mlPlugin = container "ML plugin" "TFLite Micro + esp-nn; signed models as data, LittleFS cache, Lua ml.*" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/src/ml_engine.cpp + ml_manifest.cpp"
                        "role" "plugin"
                        "horizon.intention" "Run Agent-delivered models (keyword spotting, bird calls, sensor classifiers) without reflashing"
                        "horizon.deps" "contracts + cloud_http"
                        "adl" "decisions/0006-ml-models-as-data.md"
                    }
                }

                sensorsPlugin = container "Sensors plugin" "Temp / humidity / battery (RLCD ADC, ePaper TG28 fuel gauge)" "C++" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/src/sensors.cpp"
                        "role" "plugin"
                        "horizon.deps" "contracts"
                    }
                }

                armPlugin = container "Arm plugin" "RoArm servos + motor passthrough invoke" "C++ planned" {
                    tags "Plugin"
                    properties {
                        "path" "rlcd/plugins/arm/ (planned)"
                        "role" "plugin"
                        "status" "planned"
                        "horizon.intention" "Joint control under limits; invoke bypasses Lua; no open AP JSON"
                        "horizon.deps" "contracts + wifi_nvs"
                        "adl" "ROARM-PRODUCT.md"
                    }
                }
            }

            group "L2 — infra" {
                wifiNvs = container "Wi-Fi / NVS" "STA/AP provision + cloud identity store" "C++" {
                    tags "Infra"
                    properties {
                        "path" "rlcd/src/wifi_store.cpp + wifi_ap_prov + api_config"
                        "role" "infra"
                    }
                }

                cloudHttp = container "Cloud HTTP" "tlsCloud pending/status/ack, bitmaps, model blobs; tlsLua for scripts" "C++" {
                    tags "Infra"
                    properties {
                        "path" "rlcd/src/cloud_http.cpp + main.cpp tlsLua"
                        "role" "infra"
                    }
                }

                tenancy = container "Tenancy" "Owner↔device binding; tokens" "Python" {
                    tags "Infra"
                    properties {
                        "path" "server/tenancy.py"
                        "role" "infra"
                    }
                }

                mlRegistry = container "ML registry" "Model upload, op-set check, ECDSA manifest signing, device download" "Python" {
                    tags "Infra"
                    properties {
                        "path" "server/ml_registry.py + ml_opset.py"
                        "role" "infra"
                    }
                }

                render = container "Render" "Server-side text/bitmap for panel sizes" "Python" {
                    tags "Infra"
                    properties {
                        "path" "server/render.py"
                        "role" "infra"
                    }
                }
            }
        }

        operator -> controlPlane "invoke / deploy Lua (oct_)"
        operator -> visionHost "frame → scene state (pathway B)"
        operator -> jevServoHost "goal+scene → joint intervals (pathway C)"
        jevServoHost -> visionHost "reads SceneDesc.state"
        jevServoHost -> controlPlane "single arm.stream goal per tick (oct_)"
        owner -> controlPlane "register device; mint tokens"
        deviceRuntime -> cloudHost "pending / status / ack (device_token)"
        controlPlane -> cloudHost "same deploy when self-hosted"
        armPlugin -> waveshareArm "servo bus"
        # Vision / JEV servo do NOT depend on armPlugin in-firmware; Host bridges via cloud.
        deviceRuntime -> scriptEngine "run / stop scripts"
        scriptEngine -> contracts "register modules"
        panelPlugin -> contracts "implements"
        audioPlugin -> contracts "implements"
        blePadPlugin -> contracts "implements"
        sensorsPlugin -> contracts "implements"
        armPlugin -> contracts "implements"
        claudeBuddyPlugin -> contracts "implements"
        deviceRuntime -> panelPlugin "wires when product includes panel"
        deviceRuntime -> armPlugin "wires when product includes arm"
        deviceRuntime -> claudeBuddyPlugin "pipes BLE UART bytes; passes PanelDisplay + battery"
        scriptEngine -> claudeBuddyPlugin "registers claude.*"
        mlPlugin -> contracts "implements"
        mlPlugin -> cloudHttp "signed manifest + .tflite"
        deviceRuntime -> mlPlugin "wires mic hook; status meta.ml"
        scriptEngine -> mlPlugin "registers ml.*"
        controlPlane -> mlRegistry "mounts /api/ml + device model routes"
        mlRegistry -> tenancy "device owner"
        claudeDesktop -> blePadPlugin "Hardware Buddy JSON over Nordic UART"
    }

    views {
        systemContext onlyclaws "SystemContext" {
            include *
            autoLayout
        }
        container onlyclaws "Containers" {
            include *
            autoLayout
        }
        styles {
            element "Person" { shape Person }
            element "External" { background #999999 }
            element "Plugin" { background #1168bd color #ffffff }
            element "Compose" { background #438dd5 color #ffffff }
            element "Contracts" { background #85bbf0 color #000000 }
            element "Infra" { background #cccccc color #000000 }
        }
    }
}
