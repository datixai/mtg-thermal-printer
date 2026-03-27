"""
test_hardware.py
----------------
Individual hardware component tests.
Run specific tests before assembling the full project:
  python scripts/test_hardware.py --display
  python scripts/test_hardware.py --encoder
  python scripts/test_hardware.py --printer
  python scripts/test_hardware.py --all

Datix AI | Ahmed Ali | datixai.com
"""

import sys, time, argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from config_manager import get_config, setup_logging

cfg = get_config()
setup_logging(cfg)

def test_display():
    """Test OLED display with various messages."""
    print("\n[TEST] OLED Display — SSD1306 128x64")
    print("  Wiring: SDA→GPIO2(Pin3), SCL→GPIO3(Pin5)")
    print("  Run: i2cdetect -y 1  (should see 0x3c)\n")
    from display import OLEDDisplay
    d = OLEDDisplay(cfg)
    if d.is_simulation():
        print("  ⚠ Simulation mode (no hardware detected)")
    for cmc, status in [(0,"Ready"),(5,"Fetching..."),(12,"Printing..."),(0,"Done!")]:
        print(f"  Showing CMC:{cmc} '{status}'")
        d.show(cmc, status)
        time.sleep(1)
    d.show_message("TEST DONE", "Hardware OK")
    time.sleep(2)
    d.clear()
    print("  ✓ Display test complete\n")

def test_encoder():
    """Test rotary encoder — turn and press."""
    print("\n[TEST] Rotary Encoder — KY-040")
    print("  Wiring: CLK→GPIO13(Pin33), DT→GPIO6(Pin31), SW→GPIO5(Pin29)")
    print("  Turn CW/CCW and press button. Press Ctrl+C to end.\n")
    from encoder import RotaryEncoder, EncoderEvent
    events = []
    def on_event(e):
        events.append(e)
        print(f"  Event: {e.name}")
    enc = RotaryEncoder(cfg, on_event)
    try:
        print("  Waiting for encoder input (10 seconds)...")
        time.sleep(10)
    except KeyboardInterrupt:
        pass
    finally:
        enc.stop()
    print(f"  Captured {len(events)} events")
    print("  ✓ Encoder test complete\n")

def test_printer():
    """Test thermal printer with a test receipt."""
    print("\n[TEST] Thermal Printer")
    print("  Wiring: TX→GPIO14(Pin8), RX→GPIO15(Pin10) via logic converter")
    print("  Check serial port: ls /dev/serial*\n")
    from printer import ThermalPrinter
    p = ThermalPrinter(cfg)
    if p.is_simulation():
        print("  ⚠ Simulation mode (no hardware detected)")
    fake_card = {
        "name":       "Test Card",
        "mana_cost":  "{2}{U}",
        "cmc":        3,
        "type_line":  "Instant",
        "oracle_text":"This is a test print from the Datix AI MTG Printer.\nIf you see this, the printer is working!",
        "rarity":     "common",
        "set":        "TST",
        "id":         "00000000-0000-0000-0000-000000000000",
    }
    success = p.print_card(fake_card, None)
    print(f"  Print result: {'✓ Success' if success else '✗ Failed'}")
    print("  ✓ Printer test complete\n")

def test_i2c():
    """Check I2C bus for connected devices."""
    print("\n[TEST] I2C Bus Scan")
    try:
        import subprocess
        result = subprocess.run(["i2cdetect","-y","1"], capture_output=True, text=True)
        print(result.stdout)
        if "3c" in result.stdout.lower():
            print("  ✓ OLED detected at 0x3C")
        else:
            print("  ! OLED not detected at 0x3C — check wiring")
    except Exception as e:
        print(f"  ! i2cdetect failed: {e}")
        print("  Run: sudo apt-get install i2c-tools")

def main():
    parser = argparse.ArgumentParser(description="Hardware component tests")
    parser.add_argument("--display", action="store_true", help="Test OLED display")
    parser.add_argument("--encoder", action="store_true", help="Test rotary encoder")
    parser.add_argument("--printer", action="store_true", help="Test thermal printer")
    parser.add_argument("--i2c",     action="store_true", help="Scan I2C bus")
    parser.add_argument("--all",     action="store_true", help="Run all tests")
    args = parser.parse_args()

    if args.all or args.i2c:    test_i2c()
    if args.all or args.display: test_display()
    if args.all or args.encoder: test_encoder()
    if args.all or args.printer: test_printer()

    if not any(vars(args).values()):
        parser.print_help()

if __name__ == "__main__":
    main()
