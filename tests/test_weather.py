"""NWS discovery never widens the approved host/path or fabricates missing data."""
import json
from unittest.mock import patch

import pytest

from jarvis import net, online
from jarvis.brain import Brain

URL = "https://api.weather.gov/gridpoints/PSR/159,76/forecast"


def forecast(temperature=72, unit="F"):
    return {"properties":{"updated":"2026-11-27T12:00:00Z", "periods":[{
        "name":"This Afternoon", "startTime":"2026-11-27T12:00:00-07:00", "temperature":temperature,
        "temperatureUnit":unit, "shortForecast":"Sunny", "windSpeed":"5 mph", "windDirection":"NE"}]}}


def test_coordinate_and_bounded_forecast_requests_need_approval(isolated_app):
    cfg, db, _, _ = isolated_app
    cfg["allow_internet_tools"] = True
    brain = Brain(cfg, db)
    replies=[(json.dumps({"properties":{"forecast":URL}}),"application/geo+json"),
             (json.dumps(forecast()),"application/geo+json")]
    with patch.object(net,"read_public_page",side_effect=replies) as read:
        preview=brain.ask("/weather 33.49,-111.92")
        assert "33.4900, -111.9200" in preview and "api.weather.gov" in preview
        assert not read.called and "confirm weather" in brain.ask("yes")
        result=brain.ask("confirm weather")
        assert "72 F" in result and "Sunny" in result and URL in result
        assert [call.args[0] for call in read.call_args_list] == ["https://api.weather.gov/points/33.4900,-111.9200",URL]


@pytest.mark.parametrize("lat,lon", [(91,0),(0,181),("nan",0),(0,"inf"),(True,0),("not a number",0)])
def test_invalid_coordinates_are_refused(lat,lon):
    with pytest.raises(ValueError):
        online._weather_coordinates(lat,lon)


@pytest.mark.parametrize("url", ["https://attacker.invalid/forecast", "https://api.weather.gov.evil.invalid/gridpoints/PSR/1,2/forecast",
    "https://api.weather.gov/gridpoints/PSR/1,2/forecast?secret=value", "https://user:pass@api.weather.gov/gridpoints/PSR/1,2/forecast",
    "https://api.weather.gov/stations/PRIVATE", "http://api.weather.gov/gridpoints/PSR/1,2/forecast"])
def test_discovery_cannot_redirect_approval_to_another_destination(isolated_app,url):
    _, _, ctx, _ = isolated_app
    with patch.object(net,"read_public_page",return_value=(json.dumps({"properties":{"forecast":url}}),"application/json")) as read:
        with pytest.raises(ValueError, match="approved NWS"):
            online.weather_read(ctx,33.49,-111.92)
        assert read.call_count == 1


@pytest.mark.parametrize("temperature,unit", [(None,"F"),(72,None),(float("nan"),"F"),(999,"F"),("72","F")])
def test_missing_or_invalid_temperatures_are_never_replaced(isolated_app,temperature,unit):
    cfg, _, ctx, _ = isolated_app
    cfg["allow_internet_tools"] = True
    replies=[(json.dumps({"properties":{"forecast":URL}}),"application/json"),
             (json.dumps(forecast(temperature,unit)),"application/json")]
    with patch.object(net,"read_public_page",side_effect=replies):
        with pytest.raises(ValueError):
            online.weather_read(ctx,33.49,-111.92)


def test_cancel_between_discovery_and_forecast_stops_second_read(isolated_app):
    cfg, _, ctx, _ = isolated_app
    cfg["allow_internet_tools"] = True
    def points(*args, **kwargs):
        cfg["lockdown"] = True
        return json.dumps({"properties":{"forecast":URL}}),"application/json"
    with patch.object(net,"read_public_page",side_effect=points) as read:
        assert "stopped" in online.weather_read(ctx,33.49,-111.92)
        assert read.call_count == 1
