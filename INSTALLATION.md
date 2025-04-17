# Fuktstyrning - Installationsguide

## Installation

### Metod 1: Manuell installation
1. Kopiera hela mappen `custom_components/fuktstyrning` till din Home Assistant config-mapp under `config/custom_components/`
2. Starta om Home Assistant
3. Gå till Inställningar -> Enheter och tjänster -> Lägg till integration
4. Sök efter "Fuktstyrning" och välj den

### Metod 2: Installation via HACS (Home Assistant Community Store)
1. Se till att du har HACS installerat
2. Gå till HACS -> Integrations -> tre punkter (överst till höger) -> Egna repositories
3. Lägg till URL till detta repository
4. Kategorisera som "Integration"
5. Klicka på "Lägg till"
6. Sök efter "Fuktstyrning" i HACS och installera
7. Starta om Home Assistant
8. Gå till Inställningar -> Enheter och tjänster -> Lägg till integration
9. Sök efter "Fuktstyrning" och välj den

## Konfiguration

Vid installationen kommer du behöva ange följande information:

* **Fuktighetssensor**: Välj `sensor.aqara_t1_innerst_luftfuktighet`
* **Elpris-sensor**: Välj `sensor.nordpool_kwh_se3_3_10_025`
* **Avfuktarens switch**: `switch.lumi_lumi_plug_maeu01_switch`
* **Aktiv effekt**: `sensor.lumi_lumi_plug_maeu01_active_power`
* **Plug-in temperatursensor**: `sensor.lumi_lumi_plug_maeu01_device_temperature`
* **Plug-in spänningssensor**: `sensor.lumi_lumi_plug_maeu01_rms_voltage`
* **Väderentitet** (valfritt): Om du vill använda väderdata för att förutse fuktnivåer
* **Maximal fuktighetsgräns**: Standardvärdet är 70%
* **Utomhusfuktighetssensor** (valfritt): `sensor.aqara_ute_luftfuktighet`
* **Utomhustemperatursensor** (valfritt): `sensor.aqara_ute_temperatur`
* **Utomhustrycksensor** (valfritt): `sensor.aqara_ute_tryck`
* **Temperatursensor** (valfritt): Välj `sensor.aqara_t1_innerst_temperatur`
* **Trycksensor** (valfritt): Välj `sensor.aqara_t1_innerst_tryck`
* **Energisensor (konsumerad)** (valfritt): `sensor.lumi_lumi_plug_maeu01_summation_delivered`
* **Schematid** (valfritt): Parameter `schedule_update_time` (t.ex. "13:00")

## Dashboard

För att installera dashboarden:

1. Gå till Inställningar -> Dashboards
2. Klicka på "Lägg till Dashboard" (högst upp till höger)
3. Välj "Från YAML fil"
4. Kopiera innehållet från filen `custom_components/fuktstyrning/dashboards/fuktstyrning.yaml`
5. Klistra in och spara

OBS: Du kan behöva redigera dashboarden för att anpassa enhetsnamn som passar din installation.

## Tjänster

Fuktstyrning-integrationen erbjuder flera tjänster som kan användas i automationer:

* **fuktstyrning.update_schedule**: Tvingar en uppdatering av schemat
* **fuktstyrning.reset_cost_savings**: Återställer räknaren för besparingar
* **fuktstyrning.set_max_humidity**: Ändrar temporärt den maximala fuktighetsgränsen

Exempel på hur du anropar en tjänst i en automation:

```yaml
service: fuktstyrning.update_schedule
target:
  entity_id: switch.fuktstyrning_dehumidifier_smart_control
```

## Anpassa och felsöka

* Loggar för integrationen kan hittas i Home Assistant logs under `custom_components.fuktstyrning`
* Om schemat inte skapas automatiskt kl 13:00, kontrollera att Nordpool-integrationen fungerar korrekt
* För att optimera för din specifika avfuktare, kan du behöva justera parametrarna i koden baserat på din avfuktares prestanda

## Avfuktarens prestandadata

Systemet använder följande data för att beräkna hur mycket avfuktaren behöver köras:

**Fuktsänkning**:
* 69% till 68%: ca 3 minuter
* 68% till 67%: ca 3 minuter
* 67% till 66%: ca 4 minuter
* 66% till 65%: ca 5 minuter
* 65% till 60%: ca 30 minuter

**Fukthöjning**:
* 60% till 65%: ca 1 timme
* 65% till 70%: ca 5 timmar
