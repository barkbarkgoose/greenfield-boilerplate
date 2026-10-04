# Scheduling & dispatch

How orders get a yard, a truck and a day today, and what a fuller scheduler
would add later. The order intake, account pages and staff dashboard are
reused from the mechanic site; this part is new, and only its first version
is built.

## What's built (v1)

### The pieces

| Piece | Where | Changes how often | Who edits it |
|---|---|---|---|
| Products and prices | `backend/apps/intake/pricing.py` | Seasonally | Code (one file) |
| Zip codes we serve, distance to each yard | `backend/apps/intake/data/service_area.json` | Rarely (new area, new yard) | JSON file + `build_service_area` |
| Yards, which products each one stocks | `Yard`, `YardStock` | Daily | Dispatch board, Django admin |
| Trucks, capacity, workday, days off | `Truck`, `TruckDayOff` | Daily | Dispatch board, Django admin |
| Booked loads | `OrderLoad` | Every order | Automatic; staff reassign |

Geography lives in a flat JSON lookup instead of linked tables: one entry per
zip code, with saved miles and drive minutes to each yard. A zip code that
isn't listed is outside the area: the form offers a special request instead
of an online order. `"status": "contact"` marks zips we serve by special
request only (canyon roads, long hauls). A yard missing from a zip's list
never delivers there.

```json
"80202": {
  "status": "serve",
  "city": "Denver",
  "yards": {
    "north": {"miles": 17.5, "minutes": 40},
    "west":  {"miles": 11.9, "minutes": 29}
  }
}
```

### Building and maintaining the zip table

1. Get centroids for candidate zips (the Census "ZCTA Gazetteer" file has every
   US zip with lat/lng; trim it to your region). Columns: `zip,lat,lng,city,status,note`.
   `status` is blank (distance decides), `contact` or `decline`.
2. Put yard coordinates in the admin (Yard latitude/longitude), or a
   `code,lat,lng` CSV.
3. Estimate distances (straight line × road factor, at an average speed):

   ```bash
   cd backend
   python manage.py build_service_area zips.csv \
     --serve-miles 22 --contact-miles 35 --road-factor 1.3 --mph 30 \
     --existing apps/intake/data/service_area.json \
     --out apps/intake/data/service_area.json
   python manage.py check_service_area
   ```

4. Replace numbers you know better (a mapping service, your drivers) by hand
   and add `"locked": true` to that zip. Rebuilds with `--existing` keep locked
   entries untouched.

The table is read once and cached until the file changes. To change it without
a deploy, point `SERVICE_AREA_FILE` at a file outside the repo.

The sample file (`sample_zip_centroids.csv`, `sample_network.json`) covers ~85
Denver-metro zips around three made-up yards. Coordinates are approximate,
for the demo only. `python manage.py seed_network` loads the sample yards and
trucks.

### How an order is routed (`dispatch.py`)

Each product travels in its own load (a dump bed carries one material), so
each product is split into truckloads:

1. **Sources:** yards listed for the zip, active, with the product in stock.
2. **Trucks:** the sources' trucks that are active, not off that day, on a
   delivery day (Mon–Sat, `pricing.DELIVERY_WEEKDAYS`).
3. **Cost of a load** in truck time: `LOAD_HANDLING_MINUTES` (30, loading +
   dumping) + the round trip (2 × saved minutes). A truck takes a load only if
   its remaining `workday_minutes` (600 by default) cover it, after the loads
   already booked that day.
4. **Choice:** the truck that would deliver what's left of the product in the
   least total truck time, so one tandem from a slightly farther yard beats
   three trips in a small truck. Ties go to the nearer yard, then the bigger
   truck.
5. Repeat until the product is fully loaded.

Results:

- **ok**: every load has a truck. The loads are saved with the order and hold
  that truck time, so the next customer's quote sees a busier truck.
- **no_capacity**: some loads have no truck. They're still priced (nearest
  stocking yard, standard load size) and the order is taken; the form shows
  the next date that would work (searching 21 days ahead).
- **out_of_stock**: no reachable yard has a product. Also still taken and
  priced from the nearest yard.

Staff see flagged orders on the dashboard ("Need a truck / stock"), move
loads between trucks on the order page, or press **Re-plan** after fixing
stock or trucks. Declined orders release their trucks. Changing an order's
date moves its loads (with their trucks) to the new day without re-routing,
so hand assignments survive; re-plan if the new day is busier.

Delivery is priced per load by distance from the yard it ships from
(`pricing.delivery_fee`), so the price follows the routing.

### Known limits of v1

These are deliberate simplifications, roughly in the order they'll matter.

- **A day is a bucket of minutes.** There are no time slots or routes: three
  morning loads may not actually fit in a morning. The morning/afternoon
  window is recorded and shown, not enforced.
- **One load = one trip from the truck's home yard.** Trucks never load at
  another yard, and never chain deliveries (yard → A → B → yard).
- **Distances are one number per zip.** A big rural zip can be 5 or 25 miles
  from a yard depending on the address.
- **Stock is in/out, not quantities.** Selling 300 yards from a pile of 100 is
  possible.
- **Truck time vs. customer price.** The router minimizes truck minutes. That
  is usually also the cheapest price, but not always: two short trips cost the
  customer two base delivery fees, where one longer trip might have cost less.
- **Unconfirmed orders hold trucks.** New orders book their loads on the date
  the customer asked for, before staff confirm. Fine at low volume; a backlog
  of stale "new" orders would hide capacity.
- **Everything is in cubic yards.** Gravel and rock are usually sold by the
  ton; trucks are weight-limited for heavy material.

## Deferred: a fuller scheduler

Sketched in phases so each one is useful alone. Nothing below is built.

### Phase 2: time slots and confirmed holds

- Split the workday into slots (e.g. 7–10, 10–1, 1–4), or plan start times per
  load: start = previous load's return + loading. Morning/afternoon becomes a
  constraint, and customers can pick a slot the form shows as open.
- Only `scheduled` orders hold capacity firmly; `new` orders hold it for N
  hours (a soft hold), then release it if staff haven't confirmed.
- Per-truck start/end times and a lunch break instead of a flat
  `workday_minutes`.
- A drag-and-drop day board (reorder loads, move them between trucks).

### Phase 3: real routes

- Chain loads into routes: yard → stop → stop → yard when a truck can carry
  two small orders, or reload at whichever yard is closest to the next stop.
- Exact drive times per address from a routing API (Google Routes, Mapbox,
  OSRM), cached per (yard, address). The zip table stays as the fast first
  check and the fallback when the API is down.
- Solve the day as a vehicle-routing problem with time windows (OR-Tools or a
  hosted optimizer) once there are enough loads per day for it to pay off.

### Phase 4: inventory and materials

- Yard stock as quantities (yards on hand, decremented per load, reorder
  alerts), so out-of-stock is automatic.
- Products sold by the ton with density per material, and a truck weight
  limit as well as a volume limit.
- Per-yard prices, if yards buy at different costs.

### Phase 5: drivers and customers

- A driver view: today's loads in order, map link, mark delivered with a photo.
  Marking delivered sets the order's status and starts the invoice.
- Day-before confirmation texts and "truck on the way" texts.
- Online payment or a deposit at order time.

### Decisions to make before phase 2

1. **Slots or start times?** Fixed slots are simpler to show customers; planned
   start times use trucks better.
2. **How long do unconfirmed orders hold a truck?**
3. **Can trucks load at other yards?** Changes routing from "per yard" to "per
   network".
4. **Routing API, and budget.** Per-address times cost money per lookup;
   caching by address keeps that small.
5. **What counts as a full day?** Loads per truck, hours, or both (driver hours
   rules may apply).

## Where to change things

| To change | Edit |
|---|---|
| Prices, delivery fee, rush fee, delivery days | `pricing.py` (top of file) |
| Loading/dumping time, next-date search range | `dispatch.py` (top of file) |
| Zip codes and distances | `data/service_area.json` (`build_service_area`, `check_service_area`) |
| Yards, stock, trucks, days off | Dispatch board (`/dashboard/dispatch`) or the Django admin |
| Routing rule (what "best truck" means) | `dispatch._route` (the `key` tuple) |
