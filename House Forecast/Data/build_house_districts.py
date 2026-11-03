"""
build_house_districts.py - builds Data/house_districts_2026.csv (one row per 2026 House district).

Run once (already run; re-run only if you edit the tables below):   python build_house_districts.py

Sources (checked Nov 2, 2026):
  - 2024 presidential result for every district on the lines used in 2026: The Downballot, "2020 & 2024 presidential
    election results for congressional districts used in the 2026 elections" (July 9, 2026), Google Sheet
    1eZfaFI-c-PFOoKx1-zZA2MP0_dxRq_LVK0re3BOQqy0 (saved as Data/calibration/_downballot_2026_raw.csv).
    Its "Incumbent" column is the member who currently holds that district NUMBER, not necessarily who runs there.
  - Who runs where in redrawn / checked states (AL AK AZ AR CA CO CT DE FL GA HI ID IL IN NC OH UT TN LA TX):
    Wikipedia "2026 United States House of Representatives elections" (+ the per-state pages) and 270toWin (Texas).
  - Members not running again: Ballotpedia, "List of U.S. Congress incumbents who are not running for re-election in
    2026" (counts as of Oct 2, 2026); Chuck Edwards (NC-11) withdrew Aug 5, 2026 (WFAE).
  - Nominees in the other competitive states: 270toWin state pages (Nov 2, 2026).
  - Single-party races: 270toWin "Uncontested U.S. House Races" (2026).
  - Missouri: the 2022 map is used (Missouri Supreme Court; map goes to Proposition A), as in The Downballot's sheet.
"""
import re
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RAW = HERE / "calibration" / "_downballot_2026_raw.csv"
OUT = HERE / "house_districts_2026.csv"
_REPO = HERE.parent.parent
REGIONS_FILE = next((p for p in (_REPO / "Senate Forecast" / "Data" / "leans_and_regions.csv", _REPO / "Data" / "leans_and_regions.csv") if p.exists()), _REPO / "Data" / "leans_and_regions.csv")
NATIONAL_2024_MARGIN = 48.32 - 49.81  # Harris - Trump, national popular vote (pts)

ABBR_STATE = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
              "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
              "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
              "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
              "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
              "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
              "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
              "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
              "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
              "WI": "Wisconsin", "WY": "Wyoming"}

# ---- States checked race by race: district | incumbent running HERE (blank = open) | inc party | D nominee | R nominee | other
CHECKED = """
AL-01|||Clyde Jones Jr.|Jerry Carl|
AL-02|Shomari Figures|D|Shomari Figures|Rhett Marques|
AL-03|Mike Rogers|R|Lee McInnis|Mike Rogers|
AL-04|Robert Aderholt|R|Amanda Pusczek|Robert Aderholt|
AL-05|Dale Strong|R|Andrew Sneed|Dale Strong|
AL-06|Gary Palmer|R|Maurice Mercer|Gary Palmer|
AL-07|Terri Sewell|D|Terri Sewell|Ammie Akin|
AK-AL|Nick Begich|R|Bill Hill|Nick Begich|Eric Hafner (D)
AZ-01|||Amish Shah|Jay Feely|
AZ-02|Eli Crane|R|Jonathan Nez|Eli Crane|
AZ-03|Yassamin Ansari|D|Yassamin Ansari||
AZ-04|Greg Stanton|D|Greg Stanton|Zuhdi Jasser|
AZ-05|||Elizabeth Lee|Mark Lamb|
AZ-06|Juan Ciscomani|R|JoAnna Mendoza|Juan Ciscomani|
AZ-07|Adelita Grijalva|D|Adelita Grijalva|Daniel Butierez|
AZ-08|Abraham Hamadeh|R|Bernadette Greene-Placentia|Abraham Hamadeh|
AZ-09|Paul Gosar|R|Dani Sterbinsky|Paul Gosar|
AR-01|Rick Crawford|R|Terri Green|Rick Crawford|
AR-02|French Hill|R|Chris Jones|French Hill|
AR-03|Steve Womack|R|Robb Ryerse|Steve Womack|
AR-04|Bruce Westerman|R|James Russell|Bruce Westerman|
CA-01|James Gallagher|R|Mike McGuire|James Gallagher|
CA-02|Jared Huffman|D|Jared Huffman|Robin Littau|
CA-03|Ami Bera|D|Ami Bera|Robb Tucker|
CA-04|Mike Thompson|D|Mike Thompson||Eric Jones (D)
CA-05|Tom McClintock|R|Michael Masuda|Tom McClintock|
CA-06|Kevin Kiley|I|Richard Pan||Kevin Kiley (I)
CA-07|Doris Matsui|D|Doris Matsui||Mai Vang (D)
CA-08|John Garamendi|D|John Garamendi|Rudy Recile|
CA-09|Josh Harder|D|Josh Harder|John McBride|
CA-10|Mark DeSaulnier|D|Mark DeSaulnier|Jeff Frese|
CA-11|||Scott Wiener||Connie Chan (D)
CA-12|Lateefah Simon|D|Lateefah Simon||Jamie Joyce (D)
CA-13|Adam Gray|D|Adam Gray|Kevin Lincoln|
CA-14|Aisha Wahab|D|Aisha Wahab||Melissa Hernandez (D)
CA-15|Kevin Mullin|D|Kevin Mullin|Charles Hoelter|
CA-16|Sam Liccardo|D|Sam Liccardo|Peter Soule|
CA-17|Ro Khanna|D|Ro Khanna|Ritesh Tandon|
CA-18|Zoe Lofgren|D|Zoe Lofgren|Shane Lewis|
CA-19|Jimmy Panetta|D|Jimmy Panetta|Peter Coe Verbica|
CA-20|Vince Fong|R|Sandra Van Scotter|Vince Fong|
CA-21|Jim Costa|D|Jim Costa|Kyle Kirkland|
CA-22|David Valadao|R|Randy Villegas|David Valadao|
CA-23|Jay Obernolte|R|Tessa Lynn Hodge|Jay Obernolte|
CA-24|Salud Carbajal|D|Salud Carbajal|Bob Smith|
CA-25|Raul Ruiz|D|Raul Ruiz|Joe Males|
CA-26|||Jacqui Irwin|Sam Gallucci|
CA-27|George Whitesides|D|George Whitesides|Jason Gibbs|
CA-28|Judy Chu|D|Judy Chu|April Verlato|
CA-29|Luz Rivas|D|Luz Rivas||Angelica Duenas (D)
CA-30|Laura Friedman|D|Laura Friedman|Scott Meyers|
CA-31|Gil Cisneros|D|Gil Cisneros|Eric Ching|
CA-32|Brad Sherman|D|Brad Sherman|Larry Thompson|
CA-33|Pete Aguilar|D|Pete Aguilar|Stephanie Vargas|
CA-34|Jimmy Gomez|D|Jimmy Gomez||Angela Gonzales-Torres (D)
CA-35|Norma Torres|D|Norma Torres|Mike Cargile|
CA-36|Ted Lieu|D|Ted Lieu|Houston Brignano|
CA-37|Sydney Kamlager-Dove|D|Sydney Kamlager-Dove||Samantha Mota (D)
CA-38|||Hilda Solis|Pedro Casas|
CA-39|Mark Takano|D|Mark Takano|Steve Manos|
CA-40|Young Kim|R||Young Kim|Ken Calvert (R)
CA-41|Linda Sanchez|D|Linda Sanchez|Mitch Clemmons|
CA-42|Robert Garcia|D|Robert Garcia|Brian Burley|
CA-43|Maxine Waters|D|Maxine Waters|Cristian Morales|
CA-44|Nanette Barragan|D|Nanette Barragan|Genevieve Angel|
CA-45|Derek Tran|D|Derek Tran|Chuong Vo|
CA-46|Lou Correa|D|Lou Correa|David Pan|
CA-47|Dave Min|D|Dave Min|Jenny Le Roux|
CA-48|||Marni von Wilpert|Jim Desmond|
CA-49|Mike Levin|D|Mike Levin|Armen Kurdian|
CA-50|Scott Peters|D|Scott Peters|Steve Cohen|
CA-51|Sara Jacobs|D|Sara Jacobs|Ricardo Cabrera|
CA-52|Juan Vargas|D|Juan Vargas|Jeff Belle|
CO-01|||Melat Kiros|Christy Peterson|
CO-02|Joe Neguse|D|Joe Neguse|Kelley Dennison|
CO-03|Jeff Hurd|R|Dwayne Romero|Jeff Hurd|
CO-04|Lauren Boebert|R|Eileen Laubacher|Lauren Boebert|
CO-05|Jeff Crank|R|Jessica Killin|Jeff Crank|
CO-06|Jason Crow|D|Jason Crow|Jason Clark|
CO-07|Brittany Pettersen|D|Brittany Pettersen|Tim Bennett|
CO-08|Gabe Evans|R|Manny Rutinel|Gabe Evans|
CT-01|||Luke Bronin|Amy Chai|
CT-02|Joe Courtney|D|Joe Courtney|George Austin|
CT-03|Rosa DeLauro|D|Rosa DeLauro|Chris Lancia|
CT-04|Jim Himes|D|Jim Himes|Michael Goldstein|
CT-05|Jahana Hayes|D|Jahana Hayes|Chris Shea|
DE-AL|Sarah McBride|D|Sarah McBride|Joseph Arminio|
FL-01|Jimmy Patronis|R|Gay Valimont|Jimmy Patronis|
FL-02|||Amanda Green|Austin Rogers|
FL-03|Kat Cammack|R|Seth Harp|Kat Cammack|
FL-04|Aaron Bean|R|LaShonda Holloway|Aaron Bean|
FL-05|John Rutherford|R|Rachel Grage|John Rutherford|
FL-06|Randy Fine|R|Eric Yonce|Randy Fine|
FL-07|||Bale Dalton|Ryan Elijah|
FL-08|Mike Haridopolos|R|Jennifer Jenkins|Mike Haridopolos|
FL-09|Darren Soto|D|Darren Soto|Dan Green|
FL-10|Maxwell Frost|D|Maxwell Frost||
FL-11|||James Pericola|Joe Strada|
FL-12|Gus Bilirakis|R|Kimberly Overman|Gus Bilirakis|
FL-13|Anna Paulina Luna|R|Leela Gray|Anna Paulina Luna|
FL-14|Kathy Castor|D|Kathy Castor|Mike Beltran|
FL-15|Laurel Lee|R|Robert People|Laurel Lee|
FL-16|||Kelly Kirschner|Sydney Gruters|
FL-17|Greg Steube|R|Matthew Montavon|Greg Steube|
FL-18|Scott Franklin|R|Curtis Gibson|Scott Franklin|
FL-19|||Victor Arias|Jim Schwartzel|
FL-20|Debbie Wasserman Schultz|D|Debbie Wasserman Schultz|Brent Andersen|
FL-21|Brian Mast|R|James Martin|Brian Mast|
FL-22|||Pia Dandiya|Casey Askar|
FL-23|Lois Frankel|D|Lois Frankel|Deborah Adeimy|
FL-24|||Oliver Gilbert|Te Mayonna Brown|
FL-25|Jared Moskowitz|D|Jared Moskowitz|Scott Singer|
FL-26|Mario Diaz-Balart|R|Nicole Locklin|Mario Diaz-Balart|
FL-27|Maria Elvira Salazar|R|Eliott Rodriguez|Maria Elvira Salazar|
FL-28|Carlos Gimenez|R|Phil Ehr|Carlos Gimenez|
GA-01|||Amanda Hollowell|Jim Kingston|
GA-02|Sanford Bishop|D|Sanford Bishop|Matt Day|
GA-03|Brian Jack|R|Maura Keller|Brian Jack|
GA-04|Hank Johnson|D|Hank Johnson|James Duffie|
GA-05|Nikema Williams|D|Nikema Williams|John Oscar Salvesen|
GA-06|Lucy McBath|D|Lucy McBath|Kevin Martin|
GA-07|Rich McCormick|R|Tony Kozycki|Rich McCormick|
GA-08|Austin Scott|R|Kelly Esti|Austin Scott|
GA-09|Andrew Clyde|R|Caitlyn Gegen|Andrew Clyde|
GA-10|||Pam Delancy|Houston Gaines|
GA-11|||Chris Harden|John Cowan|
GA-12|Rick Allen|R|Ceretta Smith|Rick Allen|
GA-13|||Jasmine Clark|Jonathan Chavez|
GA-14|Clay Fuller|R|Shawn Harris|Clay Fuller|
HI-01|Ed Case|D|Ed Case|Adriel Lam|
HI-02|Jill Tokuda|D|Jill Tokuda|Brenton Awa|
ID-01|Russ Fulcher|R|Kaylee Peterson|Russ Fulcher|
ID-02|Mike Simpson|R|Ellie Gilbreath|Mike Simpson|
IL-01|Jonathan Jackson|D|Jonathan Jackson|Christian Maxwell|
IL-02|||Donna Miller|Michael Noack|
IL-03|Delia Ramirez|D|Delia Ramirez|Angel Oakley|
IL-04|||Patty Garcia|Lupe Castillo|
IL-05|Mike Quigley|D|Mike Quigley|Tommy Hanson|
IL-06|Sean Casten|D|Sean Casten|Niki Conforti|
IL-07|||La Shawn Ford|Chad Koppie|
IL-08|||Melissa Bean|Jennifer Davis|
IL-09|||Daniel Biss|John Elleson|
IL-10|Brad Schneider|D|Brad Schneider|Carl Lambrecht|
IL-11|Bill Foster|D|Bill Foster|Jeff Walter|
IL-12|Mike Bost|R|Julie Fortier|Mike Bost|
IL-13|Nikki Budzinski|D|Nikki Budzinski|Jeff Wilson|
IL-14|Lauren Underwood|D|Lauren Underwood|James Marter|
IL-15|Mary Miller|R|Jennifer Todd|Mary Miller|
IL-16|Darin LaHood|R|Paul Nolley|Darin LaHood|
IL-17|Eric Sorensen|D|Eric Sorensen|Dillan Vancil|
IN-01|Frank Mrvan|D|Frank Mrvan|Barb Regnitz|
IN-02|Rudy Yakym|R|Jamee Decio|Rudy Yakym|
IN-03|Marlin Stutzman|R|Kelly Thompson|Marlin Stutzman|
IN-04|Jim Baird|R|Drew Cox|Jim Baird|
IN-05|Victoria Spartz|R|J. D. Ford|Victoria Spartz|
IN-06|Jefferson Shreve|R|Cinde Wirth|Jefferson Shreve|
IN-07|Andre Carson|D|Andre Carson|Patrick McAuley|
IN-08|Mark Messmer|R|Mary Allen|Mark Messmer|
IN-09|Erin Houchin|R|Brad Meyer|Erin Houchin|
NC-01|Don Davis|D|Don Davis|Laurie Buckhout|
NC-02|Deborah Ross|D|Deborah Ross|Eugene Douglass|
NC-03|Greg Murphy|R|Raymond Smith Jr.|Greg Murphy|
NC-04|Valerie Foushee|D|Valerie Foushee|Max Ganorkar|
NC-05|Virginia Foxx|R|Chuck Hubbard|Virginia Foxx|
NC-06|Addison McDowell|R|Cyril Jefferson|Addison McDowell|
NC-07|David Rouzer|R|Kimberly Hardy|David Rouzer|
NC-08|Mark Harris|R|Colby Watson|Mark Harris|
NC-09|Richard Hudson|R|Richard Ojeda|Richard Hudson|
NC-10|Pat Harrigan|R|Ashley Bell|Pat Harrigan|
NC-11|||Jamie Ager||
NC-12|Alma Adams|D|Alma Adams|Jack Codiga|
NC-13|Brad Knott|R|Paul Barringer|Brad Knott|
NC-14|Tim Moore|R|LaKesha Womack|Tim Moore|
OH-01|Greg Landsman|D|Greg Landsman|Eric Conroy|
OH-02|David Taylor|R|Jennifer Mazzuckelli|David Taylor|
OH-03|Joyce Beatty|D|Joyce Beatty|Cleophus Dulaney|
OH-04|Jim Jordan|R|Joshua Kolasinski|Jim Jordan|
OH-05|Bob Latta|R|Brian Shaver|Bob Latta|
OH-06|Michael Rulli|R|Elizabeth Kirtley|Michael Rulli|
OH-07|Max Miller|R|Brian Poindexter|Max Miller|
OH-08|Warren Davidson|R|Vanessa Enoch|Warren Davidson|
OH-09|Marcy Kaptur|D|Marcy Kaptur|Derek Merrin|
OH-10|Mike Turner|R|Kristina Knickerbocker|Mike Turner|
OH-11|Shontel Brown|D|Shontel Brown|Mike Kirchner|
OH-12|Troy Balderson|R|Jerrad Christian|Troy Balderson|
OH-13|Emilia Sykes|D|Emilia Sykes|Carey Coleman|
OH-14|David Joyce|R|Maria Jukic|David Joyce|
OH-15|Mike Carey|R|Don Leonard|Mike Carey|
UT-01|||Ben McAdams|Riley Owen|
UT-02|Blake Moore|R|Peter Crosby|Blake Moore|
UT-03|Celeste Maloy|R|Kent Udell|Celeste Maloy|
UT-04|Mike Kennedy|R|Jonny Larsen|Mike Kennedy|
TN-01|Diana Harshbarger|R|Kristi Burke|Diana Harshbarger|
TN-02|Tim Burchett|R|Michaela Barnett|Tim Burchett|
TN-03|Chuck Fleischmann|R|Anna Golladay|Chuck Fleischmann|
TN-04|Scott DesJarlais|R|Victoria Broderick|Scott DesJarlais|
TN-05|||Chaz Molder|Charlie Hatcher|
TN-06|||Mike Croley|Johnny Garrett|
TN-07|Matt Van Epps|R|Darden Copeland|Matt Van Epps|
TN-08|David Kustoff|R|Heidi Kuhn|David Kustoff|
TN-09|||Justin Pearson|Brent Taylor|
LA-01|Steve Scalise|R|Lauren Jewett|Steve Scalise|
LA-02|Troy Carter|D|Troy Carter||
LA-03|Clay Higgins|R|John Day|Clay Higgins|
LA-04|Mike Johnson|R|Conrad Cable|Mike Johnson|
LA-05|||Dan McKay|Michael Echols|
LA-06|||Chauna Banks|Blake Miguez|
TX-01|Nathaniel Moran|R|Yolanda Prince|Nathaniel Moran|
TX-02|||Shaun Finnie|Steve Toth|
TX-03|Keith Self|R|Evan Hunt|Keith Self|
TX-04|Pat Fallon|R|James Pearce|Pat Fallon|
TX-05|Lance Gooden|R|Chelsey Hockett|Lance Gooden|
TX-06|Jake Ellzey|R|Danny Minton|Jake Ellzey|
TX-07|Lizzie Fletcher|D|Lizzie Fletcher|Alexander Hale|
TX-08|||Laura Jones|Jessica Steinmann|
TX-09|||Leticia Gutierrez|Alex Mealer|
TX-10|||Caitlin Rourk|Chris Gober|
TX-11|August Pfluger|R|Claire Reynolds|August Pfluger|
TX-12|Craig Goldman|R|Angela Prilliman|Craig Goldman|
TX-13|Ronny Jackson|R|Mark Nair|Ronny Jackson|
TX-14|Randy Weber|R|Thurman Bartie|Randy Weber|
TX-15|Monica De La Cruz|R|Bobby Pulido|Monica De La Cruz|
TX-16|Veronica Escobar|D|Veronica Escobar|Adam Bauman|
TX-17|Pete Sessions|R|Casey Shepard|Pete Sessions|
TX-18|Christian Menefee|D|Christian Menefee|Ronald Whitfield|
TX-19|||Kyle Rable|Tom Sell|
TX-20|Joaquin Castro|D|Joaquin Castro|Edgardo Baez|
TX-21|||Kristin Hook|Mark Teixeira|
TX-22|||Marquette Greene-Scott|Trever Nehls|
TX-23|||Katy Padilla Stout|Brandon Herrera|
TX-24|Beth Van Duyne|R|Kevin Burge|Beth Van Duyne|
TX-25|Roger Williams|R|Dione Sims|Roger Williams|
TX-26|Brandon Gill|R|Steven Shook|Brandon Gill|
TX-27|Michael Cloud|R|Tanya Lloyd|Michael Cloud|
TX-28|Henry Cuellar|D|Henry Cuellar|Tano Tijerina|
TX-29|Sylvia Garcia|D|Sylvia Garcia|Martha Fierro|
TX-30|||Frederick Haynes|Everett Jackson|
TX-31|John Carter|R|Justin Early|John Carter|
TX-32|||Dan Barrios|Jace Yarbrough|
TX-33|||Colin Allred|Patrick Gillespie|
TX-34|Vicente Gonzalez|D|Vicente Gonzalez|Eric Flores|
TX-35|||Johnny Garcia|Carlos De La Cruz|
TX-36|Brian Babin|R|Rhonda Hart|Brian Babin|
TX-37|Greg Casar|D|Greg Casar|Lauren Pena|
TX-38|||Melissa McDonough|Jon Bonck|
"""

# ---- Nominees for the remaining competitive states (270toWin state pages, Nov 2, 2026; D listed first). Incumbency for
#      these states still comes from the holder + not-running list below (it agrees with 270toWin's OPEN seats).
NOMINEES_270 = """
PA-01|Bob Harvie|Brian Fitzpatrick
PA-02|Brendan Boyle|Jessica Arriaga
PA-03|Chris Rabb|Dennis Mahoney
PA-04|Madeleine Dean|Aurora Stuski
PA-05|Mary Gay Scanlon|Nick Manganaro
PA-06|Chrissy Houlahan|Marty Young
PA-07|Bob Brooks|Ryan Mackenzie
PA-08|Paige Cognetti|Rob Bresnahan
PA-09|Rachel Wallace|Dan Meuser
PA-10|Janelle Stelson|Scott Perry
PA-11|Nancy Mannion|Lloyd Smucker
PA-12|Summer Lee|James Hayes
PA-13|Beth Farnham|John Joyce
PA-14|Alan Bradstock|Guy Reschenthaler
PA-15|Ray Bilger|Glenn Thompson
PA-16|Justin Wagner|Mike Kelly
PA-17|Chris Deluzio|Tony Guy
NY-01|Christopher Gallant|Nick LaLota
NY-02|Patrick Halpin|Andrew Garbarino
NY-03|Tom Suozzi|Michael LiPetri
NY-04|Laura Gillen|Jeanine Driscoll
NY-05|Gregory Meeks|George Marsh
NY-06|Grace Meng|Joseph Chou
NY-07|Claire Valdez|Melvin Rivera
NY-08|Hakeem Jeffries|Lewis Mizrahi
NY-09|Yvette Clarke|Joel Azumah
NY-10|Brad Lander|Jennifer Moore
NY-11|Mike DeCillis|Nicole Malliotakis
NY-12|Micah Lasher|Caroline Shinkle
NY-13|Darializa Chevalier|Jomo Williams
NY-14|Alexandria Ocasio-Cortez|Diamant Hysenaj
NY-15|Ritchie Torres|Stylo Sapaskis
NY-16|George Latimer|Joseph Cinquemani
NY-17|Cait Conley|Mike Lawler
NY-18|Pat Ryan|Jackie Auringer
NY-19|Josh Riley|Peter Oberacker
NY-20|Paul Tonko|Ralph Ambrosio
NY-21|Blake Gendebien|Anthony Constantino
NY-22|John Mannion|Kailee Buller
NY-23|Aaron Gies|Nick Langworthy
NY-24|Alissa Ellman|Claudia Tenney
NY-25|Joe Morelle|Virginia McIntyre
NY-26|Tim Kennedy|Dennis Hannon
MI-01|Callie Barr|Jack Bergman
MI-02|Ben Ambrose|John Moolenaar
MI-03|Hillary Scholten|Terri DeBoer
MI-04|Sean McCann|Bill Huizenga
MI-05|Christian Vukasovich|Tim Walberg
MI-06|Debbie Dingell|Heather Smiley
MI-07|William Lawrence|Tom Barrett
MI-08|Kristen McDonald Rivet|Thomas Smith
MI-09|Ray Pooley|Lisa McClain
MI-10|Christina Hines|Michael Bouchard
MI-11|Jeremy Moss|Ethan Baker
MI-12|Rashida Tlaib|James Hooper
MI-13|Donavan McKinney|T.P. Nykoriak
IA-01|Christina Bohannan|Mariannette Miller-Meeks
IA-02|Lindsay James|Joe Mitchell
IA-03|Sarah Trone Garriott|Zach Nunn
IA-04|Dave Dawson|Chris McGowan
WI-01|Mitchell Berman|Bryan Steil
WI-03|Rebecca Cooke|Derrick Van Orden
WI-04|Gwen Moore|Tim Rogers
WI-05|Andrew Beck|Scott Fitzgerald
WI-06|Brad Smith|Glenn Grothman
WI-07|Fred Clark|Michael Alfonso
WI-08|Rick Crosson|Tony Wied
VA-01|Shannon Taylor|Rob Wittman
VA-02|Elaine Luria|Jen Kiggans
VA-03|Bobby Scott|Edwin Rivera
VA-04|Jennifer McClellan|Robert Murray
VA-05|Tom Perriello|John McGuire
VA-06|Beth Macy|Ben Cline
VA-07|Eugene Vindman|Doug Ollivant
VA-08|Don Beyer|Tony Sabio
VA-09|Joy Powers|Morgan Griffith
VA-10|Suhas Subramanyam|Dave Beckwith
VA-11|James Walkinshaw|Arthur Purves
NJ-01|Donald Norcross|Damon Galdo
NJ-02|Zack Mullock|Jeff Van Drew
NJ-03|Herb Conaway|Michael McGuire
NJ-04|Rachel Peace|Chris Smith
NJ-05|Josh Gottheimer|Sean Kirrane
NJ-06|Frank Pallone|Hillary Herzig
NJ-07|Rebecca Bennett|Tom Kean
NJ-08|Rob Menendez|Aristotle Eliopoulos
NJ-09|Nellie Pou|Rosie Pino
NJ-10|LaMonica McIver|Carmen Bucco
NJ-11|Analilia Mejia|Joe Hathaway
NJ-12|Adam Hamawy|Gregg Mele
NE-01|Chris Backemeyer|Mike Flood
NE-02|Denise Powell|Brinker Harding
NE-03|Becky Stille|Adrian Smith
ME-01|Chellie Pingree|Ronald Russell
ME-02|Matt Dunlap|Paul LePage
NV-01|Dina Titus|Carrie Buck
NV-02|Teresa Benitez-Thompson|David Flippo
NV-03|Susie Lee|Martin O'Donnell
NV-04|Steven Horsford|Cody Whipple
MN-01|Jake Johnson|Brad Finstad
MN-02|Matt Little|Eric Pratt
MN-03|Kelly Morrison|Tyler Bass
MN-04|Betty McCollum|Paul Wikstrom
MN-05|Ilhan Omar|John Nagel
MN-06|Doug Chapin|Tom Emmer
MN-07|Erik Osberg|Michelle Fischbach
MN-08|Trina Swanson|Pete Stauber
NM-01|Melanie Stansbury|Didi Okpareke
NM-02|Gabe Vasquez|Gregory Cunningham
NM-03|Teresa Leger Fernandez|Martin Zamora
NH-01|Stefany Shaheen|Anthony DiLorenzo
NH-02|Maggie Goodlander|Lily Tang Williams
MT-01|Sam Forstag|Aaron Flint
MT-02|Brian Miller|Troy Downing
WA-01|Suzan DelBene|Mary Silva
WA-02|Rick Larsen|Edwin Feller
WA-03|Marie Gluesenkamp Perez|John Braun
WA-04|John Duresky|Amanda McKinney
WA-05|Carmela Conroy|Michael Baumgartner
WA-06|Emily Randall|Teresa Fox
WA-07|Pramila Jayapal|Nirav Sheth
WA-08|Kim Schrier|Spencer Meline
WA-09|Adam Smith|Doug Basler
WA-10|Marilyn Strickland|Chris Chung
KY-01|John Williams|James Comer
KY-02|Megan Wingfield|Brett Guthrie
KY-03|Morgan McGarvey|Maria Rodriguez
KY-04|Melissa Strange|Ed Gallrein
KY-05|Ned Pillersdorf|Hal Rogers
KY-06|Zach Dembo|Ralph Alvarado
SC-01|Nancy Lacore|Jenny Honeycutt
SC-02|Zyon Khalifa|Joe Wilson
SC-03|Eunice Lehmacher|Sheri Biggs
SC-04|Courtney McClain|William Timmons
SC-05|Mallory Dittmer|Wes Climer
SC-06|Jim Clyburn|John Peterson
SC-07|John Vincent|Russell Fry
MO-01|Wesley Bell|Paul Berry
MO-02|Fred Wellman|Ann Wagner
MO-03|Bethany Mann|Bob Onder
MO-04|Jordan Herrera|Mark Alford
MO-05|Emanuel Cleaver|Rick Brattin
MO-06|Josh Smead|Chris Stigall
MO-07|Missi Hesketh|Eric Burlison
MO-08|Chris Reichard|Jason Smith
KS-01|Lauren Reinhold|Tracey Mann
KS-02|Don Coover|Derek Schmidt
KS-03|Sharice Davids|Eric Jenkins
KS-04|Katy Tyndell|Ron Estes
OR-01|Suzanne Bonamici|Barbara Kahl
OR-02|Chris Beck|Cliff Bentz
OR-03|Maxine Dexter|Loran Ayles
OR-04|Val Hoyle|Monique DeSpain
OR-05|Janelle Bynum|Patti Adair
OR-06|Andrea Salinas|David Russ
MD-01|Dan Schwartz|Andy Harris
MD-02|Johnny Olszewski|Dave Wallace
MD-03|Sarah Elfreth|Berney Flowers
MD-04|Glenn Ivey|George McDermott
MD-05|Adrian Boafo|Chris Chaffee
MD-06|April McClain Delaney|Robin Ficker
MD-07|Kweisi Mfume|Scott Collier
MD-08|Jamie Raskin|Cheryl Riley
"""

# ---- Everyone else: the member holding the district number runs again unless listed here (surnames, by state)
NOT_RUNNING = {"MO": ["Graves"], "MT": ["Zinke"], "NV": ["Amodei"], "MD": ["Hoyer"],
               "NY": ["Stefanik", "Velazquez", "Nadler", "Espaillat", "Goldman"], "WA": ["Newhouse"],
               "NJ": ["Watson Coleman"], "ME": ["Golden"], "NE": ["Bacon"], "PA": ["Evans"], "OK": ["Hern"],
               "WY": ["Hageman"], "MA": ["Moulton"], "IA": ["Hinson", "Feenstra"], "KY": ["Barr", "Massie"],
               "MI": ["Stevens", "James", "Thanedar"], "MN": ["Craig"], "NH": ["Pappas"], "WI": ["Tiffany"],
               "SC": ["Mace", "Norman"], "SD": ["Johnson"]}

# ---- Races without a Democrat AND a Republican on the November ballot (270toWin; Wikipedia for CA-06 / CA-40)
# "D_only": Democrat unopposed or only minor-party opposition | "DD" / "RR": same-party top-two | "IND": D vs independent
RACE_TYPE = {"FL-10": "D_only", "MA-02": "D_only", "MA-05": "D_only", "MA-07": "D_only", "WI-02": "D_only",
             "LA-02": "D_only", "MA-01": "D_only", "PA-03": "D_only",  # NJ-08: 270toWin's state page lists a Republican

             "CA-04": "DD", "CA-07": "DD", "CA-11": "DD", "CA-12": "DD", "CA-14": "DD", "CA-29": "DD", "CA-34": "DD",
             "CA-37": "DD", "CA-40": "RR", "CA-06": "IND", "AK-AL": "IND"}
NOTES = {"AK-AL": "Bill Hill (independent, backed by national Democratic groups) vs Nick Begich (R); Eric Hafner (D) also on the ballot",
         "CA-06": "Kevin Kiley (independent, formerly R) vs Richard Pan (D); no Republican on the ballot",
         "CA-40": "Two Republican incumbents (Young Kim, Ken Calvert) face each other",
         "LA-01": "Louisiana: all-party primary Nov 3, runoff Dec 12 if no majority (new 2026 map)",
         "MO-05": "Missouri uses the 2022 map in 2026 (new map blocked; Proposition A on the ballot)",
         "NC-11": "Chuck Edwards withdrew Aug 5, 2026; Republican replacement nominee",
         "TN-09": "Redrawn Memphis seat (R-leaning); Cohen not running"}


def surname(n):
    s = re.sub(r"[^a-z\- ]", "", str(n).lower().replace("jr.", "").replace("iii", "")).strip()
    return s.split()[-1] if s else ""


def main():
    raw = pd.read_csv(RAW)
    regions = pd.read_csv(REGIONS_FILE, encoding="utf-8-sig") \
        if (REGIONS_FILE).exists() else None
    checked = {}
    for line in CHECKED.strip().splitlines():
        d, inc, ip, dn, rn, oth = (x.strip() for x in line.split("|"))
        checked[d] = dict(incumbent=inc, incumbent_party=ip, dem_candidate=dn, rep_candidate=rn, other_candidate=oth)
    nom270 = {l.split("|")[0]: tuple(l.split("|")[1:3]) for l in NOMINEES_270.strip().splitlines()}
    rows = []
    for _, r in raw.iterrows():
        d = r["district"]
        st = d[:2]
        holder = str(r["incumbent"])
        hp = str(r["party"]).strip("()")
        if d in checked:
            c = checked[d]
            src = "checked race by race"
        else:
            vacant = holder.upper().startswith("VACANT")
            out = vacant or any(surname(holder) == surname(n) for n in NOT_RUNNING.get(st, []))
            c = dict(incumbent="" if out else holder, incumbent_party="" if out else hp,
                     dem_candidate=holder if (hp == "D" and not out) else "",
                     rep_candidate=holder if (hp == "R" and not out) else "", other_candidate="")
            src = "holder + not-running list"
            if d in nom270:
                c["dem_candidate"], c["rep_candidate"] = nom270[d]
                src += " + 270toWin nominees"
        rows.append({
            "district": d, "state": ABBR_STATE[st], "state_abbr": st,
            "harris24": r["harris24"], "trump24": r["trump24"], "pres24_margin": r["margin24"],
            "partisan_lean": round((float(r["margin24"]) - NATIONAL_2024_MARGIN) / 2, 2),
            "pres20_margin": r["margin20"],
            "holder": holder, "holder_party": hp,
            "incumbent": c["incumbent"], "incumbent_party": c["incumbent_party"],
            "status": "running" if c["incumbent"] else "open",
            "dem_candidate": c["dem_candidate"], "rep_candidate": c["rep_candidate"], "other_candidate": c["other_candidate"],
            "race_type": RACE_TYPE.get(d, "DR"), "candidates_source": src, "notes": NOTES.get(d, ""),
        })
    df = pd.DataFrame(rows)
    if regions is not None:
        df = df.merge(regions[["State", "Region"]].rename(columns={"State": "state", "Region": "region"}), on="state", how="left")
    assert len(df) == 435 and df["district"].is_unique
    df.to_csv(OUT, index=False)
    print(f"{OUT.name}: {len(df)} districts | open {int((df['status'] == 'open').sum())} | "
          f"race types {df['race_type'].value_counts().to_dict()}")


if __name__ == "__main__":
    main()
