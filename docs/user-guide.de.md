# Anleitung für das Team

Dein Unternehmen arbeitet mit **Abteilungs-Assistenten**: KI-Kollegen für
Tech, Vertrieb, Finanzen und so weiter. Du erreichst sie an zwei Orten:

- **Matrix** (die Chat-App): Sprich mit dem Assistenten deiner Abteilung im
  Raum deiner Abteilung, wie mit einem Kollegen.
- **Team Portal** (diese Website): das Arbeits-Board, Entwürfe, die auf deine
  Prüfung warten, und dein Profil.

Diese Seite findest du auch im Portal unter **Hilfe**; sie wächst mit, wenn
Neues dazukommt (siehe [Was ist neu](#was-ist-neu) am Ende). Oben rechts
wechselst du die Sprache.

[TOC]

## Erste Schritte

Du brauchst drei Dinge, die dir die Person gibt, die dein Konto eingerichtet
hat: deine **Matrix-ID** (`@name:{{HOST}}`), ein **Startpasswort** und den
Zugang zum Firmennetz (**Tailscale**, eine App auf deinem Telefon oder
Laptop, die eingeschaltet sein muss).

1. **Tailscale installieren** und wie angewiesen anmelden; eingeschaltet lassen.
2. **Eine Matrix-App installieren**: *Element X* (iPhone, Android) oder
   *Element* (Desktop), oder Element im Browser unter `https://{{HOST}}:8443`.
3. **In der App anmelden**: „anderer Server“ wählen bzw. den Homeserver auf
   `{{HOST}}` ändern, dann dein Benutzername (der Teil deiner Matrix-ID vor
   dem Doppelpunkt) und das Startpasswort.
4. **Einladungen annehmen**: Du wirst in die Räume deiner Abteilungen
   eingeladen (und in eine Direktnachricht von **Portal**, die deine
   Anmeldelinks fürs Portal liefert). Solange du nicht annimmst, bist du nicht
   im Raum, und der Assistent sieht nicht, was du schreibst.
5. **Im Portal anmelden** unter `https://{{HOST}}:10000` mit deinem
   Benutzernamen (`@name`; die vollständige Matrix-ID geht auch).
   Ein Anmeldelink kommt als Direktnachricht von Portal; öffne ihn innerhalb
   von 10 Minuten. Auf einem anderen Gerät als dem, das ihn angefordert hat,
   fragt das Portal zuerst nach einer Bestätigung.
6. **Passwort ändern** im Portal: **Profil › Passwort ändern** (die
   Mobil-Apps können das nicht). Deine angemeldeten Apps bleiben angemeldet.

**Sprache.** Das Portal und diese Anleitung erscheinen in der Sprache deines
Browsers (Deutsch oder Englisch); oben rechts stellst du sie fest ein. Unter
**Profil › Sprache** legst du fest, in welcher Sprache dich Anmeldelinks und
Erinnerungen erreichen. Die Assistenten antworten in der Sprache, in der du
schreibst. Die Element-App folgt der Sprache deines Geräts.

## Matrix: Arbeiten mit deinem Assistenten

Öffne den Raum deiner Abteilung (zum Beispiel **Tech**) und schreib ganz
normal:

- „Was liegt auf unserem Board?“
- „Lege eine Karte an: Lieferantenvergleich Q3 vorbereiten, fällig Freitag.“
- „Recherchiere die drei grössten Wettbewerber von … und fasse sie in einer Tabelle zusammen.“
- „Entwirf eine Antwort auf diese Kundenfrage: …“

**Jede neue Nachricht im Raum beginnt einen Thread**, und der Assistent
antwortet darin. Um dasselbe Gespräch fortzusetzen (seine Frage beantworten,
ein Detail ergänzen, die gewünschte Datei schicken), **antworte in diesem
Thread**; eine neue Nachricht im Raum beginnt ein neues Gespräch, das das
frühere nicht kennt. Alle im Raum können jeden Thread lesen.
Er antwortet nur Personen, die für diese Abteilung eingetragen sind; Personen
aus anderen Abteilungen können den Assistenten deines Raums nicht nutzen.

### Was der Assistent kann

| Werkzeug | Was es für dich bedeutet |
|---|---|
| Kanban-Board | Liest, erstellt und kommentiert die Karten deiner Abteilung; bringt Arbeit voran und legt dir Entwürfe zur Prüfung vor |
| Websuche und Lesen | Schlägt Dinge nach und liest Webseiten, mit Quellen |
| Gedächtnis | Merkt sich dauerhafte Vorlieben und Fakten, die du ihm nennst („antworte immer auf Deutsch“) |
| Skills | Wiederverwendbare Abläufe, die er für deine Abteilung gelernt hat |
| Rückfragen | Fragt nach, wenn eine Anfrage mehrdeutig ist, statt zu raten |
| To-do-Planung | Zerlegt grössere Anfragen in Schritte und arbeitet sie ab |
| Bilder, Sprache (Vorschau) | Kann auf Wunsch ein Bild oder eine Audiofassung einer Antwort erzeugen |
| Firmenwissen (Tech, Vorschau) | Schlägt strukturierte Firmendaten nach und erfasst sie (Organisationen, Kontakte, Projekte) |

Er **kann nicht** Programme ausführen, Dateien auf dem Server öffnen oder
die Boards anderer Abteilungen erreichen. Alles, was er für eine
Entscheidung erstellt, geht in die **Entwürfe** des Portals, wo ein Mensch
es freigibt.

### Slash-Befehle

Tippe sie als eigene Nachricht. Dein Konto darf ausführen:

| Befehl | Was er tut |
|---|---|
| `/help` | Listet die Befehle, die du nutzen kannst |
| `/whoami` | Zeigt deine Zugriffsstufe und deine Befehle |
| `/new` | Beginnt ein neues Gespräch in diesem Thread (vergisst den Kontext; fragt nach Bestätigung) |
| `/retry` | Schickt deine letzte Nachricht erneut |
| `/undo` | Nimmt deine letzte Nachricht und die Antwort darauf zurück |
| `/stop` | Stoppt, was der Assistent gerade tut |
| `/btw <Frage>` | Eine kurze Nebenfrage, ohne die laufende Aufgabe zu stören |
| `/queue <Nachricht>` | Stellt eine Nachricht für nach der laufenden Aufgabe in die Warteschlange |
| `/steer <Nachricht>` | Korrigiert die laufende Aufgabe, ohne sie zu stoppen |
| `/title <Name>` | Benennt das Gespräch |
| `/status` | Zeigt den Zustand des Gesprächs (Modell, wie voll der Kontext ist) |
| `/compress` | Kürzt ein langes Gespräch, damit der Assistent aufmerksam bleibt |

Die Befehle selbst bleiben englisch. Andere Befehle (Modell wechseln,
Neustart, Updates) sind für die Betreiber; der Assistent sagt es dir, wenn
du einen davon versuchst.

### Tipps

- Eine Anfrage pro Nachricht funktioniert am besten; sag, wie „fertig“ aussieht.
- Um eine Datei mit einer Anfrage zu schicken, hänge sie an und schreib die
  Anfrage als Bildunterschrift der Datei, oder schick die Datei im Thread.
- Während er arbeitet, siehst du kurze Statuszeilen (zum Beispiel
  „kanban_list…“). Wenn du währenddessen schreibst, korrigiert das die
  laufende Aufgabe.
- Kommt innerhalb einer Minute nichts zurück, prüfe, ob du dem Raum
  beigetreten bist (nicht nur eingeladen) und ob Tailscale an ist, dann
  `/retry`.
- Direkt nachdem sich der Zugang einer Person geändert hat, starten die
  Assistenten für ein paar Sekunden neu; eine genau in diesem Moment
  gesendete Nachricht braucht vielleicht ein `/retry`.

## HR: Rekrutieren mit dem Assistenten

Im Raum **HR** führt der Assistent die Rekrutierungsdaten: offene Stellen,
Kandidatinnen und Kandidaten mit ihren Lebensläufen und der Stand jeder
Bewerbung. Menschen entscheiden; der Assistent bereitet vor und erfasst.

| Du sagst | Was passiert |
|---|---|
| „Lege aus dieser Stellenbeschreibung eine Stelle an“ (mit der Datei) | Legt die Stelle mit prüfbaren Muss-Kriterien an; weist auf Formulierungen hin, die diskriminieren könnten („junges Team“, „Muttersprachler“) |
| „Füge Erika Testfrau zur Backend-Stelle hinzu“ (mit CV und Zeugnissen) | Erfasst die Person, speichert die Dokumente, legt die Bewerbung in der Stufe *neu* an |
| „Alle Bewerbungen für die Backend-Stelle sind in diesem ZIP“ (dann das ZIP im Thread) | Sortiert die Dokumente nach Person, zeigt dir den Plan und fügt nach deinem Ja alle Personen mit ihren Dokumenten hinzu. Ein ZIP gehört zu einer Stelle: Unterlagen für eine andere Stelle werden beiseitegelegt, damit du sie getrennt schickst |
| „Shortlist der besten 5 für die Backend-Stelle“ | Vergleicht die Personen anhand der Kriterien der Stelle, auf Lebensläufen mit ausgeblendeten Namen und persönlichen Angaben; die Shortlist landet im Portal unter **Entwürfe** zur Prüfung |
| „Interview 1 mit Erika erledigt: …“, „zweite Runde“, „Entscheidung offen“ | Bringt die Bewerbung weiter: neu → geprüft → interviewt → Entscheidung → (weitere Runde) → eingestellt / abgelehnt |
| „Max absagen, Grund: keine Kubernetes-Erfahrung“ | Bittet um Bestätigung, dann erfasst er die Entscheidung mit deinem Namen |
| „Wo stehen wir bei der Backend-Stelle?“ | Überblick nach Stufe, mit dem, was wartet |
| „Lösche alles über Lena“ | Löscht die Person mit allen Bewerbungen und Dokumenten, nach deiner Bestätigung |

Gut zu wissen:

- Schick Lebensläufe als **PDF, DOCX oder Text**, einzeln oder als **ZIP**
  (bis 25 MB und 200 Dokumente), am selben Tag (Uploads werden nach 24
  Stunden gelöscht). Fotos werden nicht gespeichert.
- Der Assistent erfasst nie Geburtsdatum, Alter, Foto, Geschlecht,
  Nationalität, Familie, Religion oder Gesundheit und bewertet nicht danach.
- Kandidatendaten werden **6 Monate** nach der letzten Aktivität
  **automatisch gelöscht**.
- Einstellungsentscheidungen triffst du: Der Assistent entscheidet nicht und
  sagt nicht in deinem Namen reihenweise ab.
- Checklisten für Onboarding und Offboarding gibt es als **Entwürfe**: Frag
  danach, aber sie führen noch keine Daten.

## Vertrieb: der Funnel mit dem Assistenten

Im Raum **Sales** führt der Assistent die Vertriebsdaten: Firmen, Kontakte,
Deals und jeden Kontaktpunkt. Er entwirft Nachrichten; **du sendest sie**.
Er kontaktiert nie selbst jemanden und schlägt nie von sich aus Personen
nach.

Der Funnel wird pro Unternehmen festgelegt: **klein** (Prospect → Offer →
Client oder Declined) oder **erweitert** (Lead → Prospect → Needs → Offer →
Client oder Declined). Ein Angebot kann für eine weitere Runde einen Schritt
zurück; ein abgelehnter Deal kann wieder geöffnet werden.

| Du sagst | Was passiert |
|---|---|
| „Neuer Lead von LinkedIn: Petra Muster, Head of Operations bei der Musterbau AG …“ | Erfasst Firma, Kontakt und Deal in der ersten Stufe. Fragt, wie wir die Person kontaktieren dürfen, wenn das nicht klar ist (siehe *Kontaktgrundlage* unten) |
| „Ich kenne sie persönlich, von der Messe“ | Erfasst die Grundlage *persönlicher Kontakt* mit deinem Namen: Jeder Kanal ist erlaubt |
| „Fünf Leads aus meiner Sales-Navigator-Liste:“ + einer pro Zeile | Erfasst sie alle und zeigt eine Tabelle; wer auf der Nicht-kontaktieren-Liste oder schon erfasst ist, wird übersprungen |
| „Entwirf eine LinkedIn-Nachricht / Instagram-DM / WhatsApp / E-Mail an Petra“ | Ein Entwurf in ihrer Sprache, aus dem, was die Daten hergeben. Du sendest ihn und sagst dann „gesendet“ |
| „Sie hat geantwortet: …“ | Protokolliert die Antwort mit Stimmung und Einwand und schlägt die nächste Stufe vor |
| „Musterbau ist jetzt Prospect“, „sie brauchen …“, „Angebot gesendet, CHF 24k“ | Bringt den Deal weiter und erfasst die Fakten dieser Stufe |
| „Sie haben unterschrieben“ | Markiert den Deal als gewonnen und nimmt den Kontakt in die Kunden-Nurture-Kampagne auf |
| „Sie haben abgelehnt: zu teuer“ | Erfasst die Absage mit einem Grund aus der Liste deines Unternehmens; je nach Grund bleibt der Kontakt im Nurture, fällt heraus, oder du wirst gefragt |
| „Sie wollen keinen Kontakt mehr von uns“ | Lehnt den Deal ab und setzt die Kennungen des Kontakts dauerhaft auf die **Nicht-kontaktieren-Liste** |
| „Wo stehen wir mit Musterbau?“, „Was ist im Funnel?“, „Was hängt?“ | Status eines Deals, oder Anzahl pro Stufe, überfällige nächste Schritte und letzte Absagen nach Grund |

**Kontaktgrundlage**: Jeder Kontakt hält fest, wie wir ihn erreichen dürfen.
*Plattform* (auf LinkedIn oder Instagram gefunden) erlaubt nur Nachrichten
innerhalb dieser Plattform; *Inbound* (sie haben uns geschrieben),
*Einwilligung*, eine *bestehende Beziehung* oder ein *persönlicher Kontakt*
erlauben auch E-Mail und WhatsApp. Sonst verweigert der Assistent eine kalte
E-Mail oder WhatsApp-Nachricht: Unverlangte Nachrichten an Personen in
Deutschland und der Schweiz sind gesetzlich eingeschränkt.

Gut zu wissen:

- Nur Geschäftsdaten: Funktion, Firma, geschäftliche E-Mail, geschäftliche
  Telefonnummer, LinkedIn- und Instagram-Handles. Nichts Privates über die
  Person.
- Kontakte, Deals und Kontaktpunkte werden **ein Jahr** nach der letzten
  Aktivität **automatisch gelöscht** (dein Unternehmen kann eine andere
  Frist festlegen).
- Die **Nicht-kontaktieren-Liste** wird nie geleert, auch nicht, wenn ein
  Kontakt gelöscht wird: Wer widersprochen hat, bleibt geschützt.
- Die Kachel **Funnel** auf dem Dashboard zählt stündlich aus diesen Daten
  die Deals pro Stufe, Konversion und Abbruch pro Schritt sowie Absagen
  nach Grund.
- **Firmenfakten** (Branche, Grösse, Website, Ort) füllt ein stündlicher
  Anreicherungslauf; frag „Was wissen wir über X?“ Der Assistent sagt dir,
  woher ein Fakt stammt.
- **Nurture**: Gewonnene Deals (und abgelehnte, deren Grund es erlaubt)
  nehmen den Kontakt in die Nurture-Kampagne auf. Freitags erscheint pro
  fälligem Schritt eine Karte für den Assistenten; sein Entwurf landet unter
  **Entwürfe** zu deiner Freigabe, und du sendest ihn. „Nimm X aus dem
  Nurture“ beendet es.

## Eine Website in die Daten einlesen

Jeder Assistent kann für sein Team eine Website lesen. Poste die Adresse im
Raum des Teams und sag, was du daraus willst:

| Wo | Du sagst | Der Assistent schlägt vor |
|---|---|---|
| #sales | „Lies https://example.ch und übernimm unsere Angebote und idealen Kunden“ | Angebote (Name, Stufe, Inhalt, öffentlicher Preis) und ideale Kundenprofile (Branche, Grösse, Länder, Rolle, Schmerzpunkt, Auslöser) |
| #hr | „Übernimm die offenen Stellen von https://example.ch/karriere“ | Eine Stelle pro Ausschreibung mit ihren Kriterien |
| jeder andere Raum | „Was macht diese Firma?“ | Eine Zusammenfassung als Entwurf unter **Entwürfe** |

Er liest die Seite und ein paar verlinkte Seiten derselben Website, meldet
sich nie an und übernimmt nie Namen oder Kontaktdaten von Personen. Du
bekommst einen **nummerierten Vorschlag**; antworte mit den Nummern, die
bleiben sollen („alle“, „1 und 3“), mit Änderungen („2: Preis 490 pro
Monat“, „4 streichen“). **Nichts wird gespeichert, bevor du bestätigst.**
Bestätigte Einträge landen als Entwürfe (Angebote, Kundensegmente, Stellen),
die der Team-Owner aktiviert. Ist eine Website für den Assistenten nicht
erreichbar (eine interne Adresse), füge stattdessen den Seitentext ein und
nenne die Adresse.

## Team Portal

### Dashboard (deine Startseite)

Das Portal öffnet sich auf dem Dashboard deines Teams. Wähle oben ein
anderes Team, wenn du zu mehreren gehörst; die Leitung sieht zuerst eine
Kachel pro Team.

- **Ziele** für den Zeitraum (Quartal) mit ihren **Key Results**: der
  aktuelle Wert gegenüber dem Zielwert, ein Fortschrittsbalken und ein
  Status: *auf Kurs*, *gefährdet* oder *vom Kurs abgekommen* gemessen daran,
  wo die Quartalslinie heute steht, *erreicht* bei 100 %.
- **KPIs**: die Zahlen, die das Team laufend beobachtet, mit Trendlinie und
  Farbe: grün innerhalb des Ziels, gelb jenseits der Warnschwelle, rot
  jenseits der kritischen. Board-KPIs (erledigte Karten, Durchlaufzeit,
  Karten in Prüfung) und HR-KPIs (offene Stellen, Pipeline-Grösse, Zeit bis
  zur Einstellung: nur Zahlen, nie eine Person) werden automatisch jede
  Stunde gemessen, wenn sich etwas geändert hat, und jeden Morgen um 06:00.
- **Arbeit**: Karten, die auf deine Freigabe warten, blockierte, laufende
  und diese Woche erledigte. Klick eine an, um sie zu öffnen.
- **Wochenrückblicke**: Jeden Montag schreibt der Team-Assistent einen
  Rückblick auf die Woche (Ziele, KPIs neben dem Ziel, das Board, drei
  Dinge, die Aufmerksamkeit brauchen) als Karte in Review. Jemand mit
  Freigaberecht liest ihn im Portal und gibt ihn frei (oder fordert
  Änderungen an); freigegebene Rückblicke erscheinen hier. Freitags
  erinnert der Assistent den Raum an Key Results ohne Check-in in dieser
  Woche.

**Check-in.** Jedes Teammitglied kann den aktuellen Wert eines Key Results
oder einer KPI erfassen: *Check-in* daneben, die Zahl eingeben und, wenn du
magst, was sie bewegt hat. Es wird unter deinem Namen mit Datum
gespeichert; der Status folgt innerhalb einer Stunde.

**Festlegen (Team-Owner, also Personen mit Freigaberecht für das Team).**
*Neues Ziel* und *Neue KPI* oben, *Key Result hinzufügen* und *bearbeiten*
an jedem Eintrag. Halte Key Results messbar: eine Zahl mit Start, Ziel und
Richtung. **Gemessen durch** entscheidet, wer den Wert liefert:

| Gemessen durch | Wer | `Metrik` |
|---|---|---|
| manual | Menschen, über Check-ins | – |
| board | das Kanban-Board, automatisch | `board.throughput window=7d`, `board.created`, `board.open`, `board.blocked`, `board.in_review`, `board.failures`, `board.cycle_time_p50_h`, `board.review_turnaround_p50_h` |
| records | die Daten des Teams (HR, Vertrieb), automatisch, nur Zahlen | `hr.open_roles`, `hr.candidates`, `hr.applications stage=interviewed`, `hr.hired window=30d`, `hr.time_to_hire_p50_d`, `sales.funnel stage=offer` |
| agent | der Team-Assistent aus einer registrierten Quelle (kommt) | – |

*Löschen* entfernt ein Ziel mit seinen Key Results und deren Verlauf; die
Daten behalten, wer was wann gelöscht hat. Du kannst den Team-Assistenten
auch im Chat fragen („Wie stehen wir bei den Zielen?“, „Check-in: Leads =
42“).

**In ein anderes Team verschieben.** Etwas im falschen Team angelegt? *In
anderes Team verschieben* an einem Ziel nimmt es, seine Key Results mit
Verlauf und die zugehörigen KPIs (das Feld *Ziel* einer KPI) in ein Team
mit, in dem du Mitglied bist; *verschieben* an einer KPI verschiebt nur
diese. Die Owner des anderen Teams sehen es sofort auf ihrem Dashboard.

**Swimlanes (Team-Owner).** Jedes Team legt seine eigenen Lanes für das
Board fest: die Arbeitsströme, die es betreibt (ein Produkt, ein Kunde, eine
wiederkehrende Pflicht). Eine Lane kann auf das Ziel zeigen, auf das sie
hinarbeitet, und auf die KPI, die sie bewegt; das Dashboard listet jede
Lane mit ihren offenen Karten, und *Board* daneben öffnet das Board
gefiltert auf diese Lane. Archiviere eine Lane, die du nicht mehr nutzt;
ihre Karten bleiben, nur ohne Lane.

### Das Board

Die Spalten folgen der Arbeit: **Triage** (neue Ideen, die der Assistent
ausformt), **Todo / Ready** (wartend), **In Arbeit** (jemand ist dran),
**Review** (ein Entwurf wartet auf eine Entscheidung), **Blockiert**,
**Erledigt**.

- **+** an einer Spalte legt eine Karte an. Wähle den Abteilungs-Assistenten
  als Zuständigen, wenn er die Arbeit machen soll; er nimmt die Karte
  innerhalb einer Minute auf.
- Ziehe Karten zwischen den Spalten. Manche Wechsel sind nicht erlaubt (nur
  Reviewer schliessen eine Karte ab oder bewegen sie aus Review); das Portal
  sagt, warum.
- Klick eine Karte für Details, Kommentare und angehängte Dateien (bis 25 MB).
- **Lanes.** Hat das Team Swimlanes, gruppiert jede Spalte ihre Karten nach
  Lane (Farbstreifen und Name), Karten ohne Lane zuletzt. Wähle die Lane,
  wenn du eine Karte anlegst, oder ändere sie auf der Karte; das kann jedes
  Teammitglied.
- **Filter** oben nehmen jeweils mehrere Werte: Wähle ein Team, eine Person,
  eine Lane, ein Fälligkeitsfenster oder eine Priorität aus der Liste, und
  sie wird zu einem Chip; wähle mehr, um zu erweitern, × an einem Chip
  entfernt ihn, *Zurücksetzen* leert alles.
- **Beteiligte** an einer Karte: ein *Owner* (verantwortlich), *Reviewer*
  und *Beobachter*. Jedes Teammitglied kann einer Karte als Beobachter
  folgen; Personen mit Freigaberecht benennen Owner und Reviewer. Benennt
  eine Karte Reviewer, können nur sie sie freigeben. Eine Karte kann *auf
  ein Key Result einzahlen* (wähle eines beim Anlegen oder am Eintrag des
  Owners): Das Dashboard listet sie dann unter diesem Key Result.
- **Der Thread der Karte im Chat.** Wird eine Karte angelegt, postet der
  Team-Assistent sie im Teamraum; was danach mit ihr passiert (erledigt,
  blockiert, Kommentare, Verschiebungen, Prüfungen) landet in diesem Thread
  und nennt die Beteiligten, damit sie benachrichtigt werden. Antworte im
  Thread, um mit dem Assistenten über die Karte zu sprechen. *Thread der
  Karte im Chat öffnen* auf der Karte.

Du siehst nur die Karten deiner Abteilungen (die Leitung sieht alle).

### Entwürfe prüfen

**Entwürfe** öffnet sich mit den Karten in Review, die du sehen darfst, und
darunter **Alle Dateien**: jede Datei an einer Karte, die du sehen kannst
(die Assistenten hängen ihre Entwürfe als `.md`-Dateien an), mit Karte,
Team, Lane, Status, Owner (der Owner der Karte, sonst wer sie hochgeladen
oder angelegt hat) und benannten Reviewern. Filtere nach Team, Lane, Owner,
Reviewer, Status und Zeitraum; klick auf eine Spaltenüberschrift zum
Sortieren. Öffne die Datei im Browser oder lade sie herunter; klick auf die
Karte, um zu prüfen.

- Öffne den Anhang (PDFs, Bilder und Text zeigt der Browser an; andere
  Dateien werden heruntergeladen).
- **Freigeben** schliesst die Karte ab; dein Name wird mit der Freigabe
  festgehalten.
- **Änderungen anfordern**: Sag konkret, was sich ändern soll. Die Karte
  geht zurück an den Assistenten, der sie überarbeitet und wieder vorlegt.
- Das Abzeichen zeigt, wie viel Zeit bleibt. Karten mit einer Autonomiestufe
  sagen, was bei Fristablauf passiert: „braucht deine Entscheidung“ (nie für
  dich entschieden) oder „wird in N h automatisch freigegeben, falls du
  nicht widersprichst“. Ohne Stufe gilt nach 48 h die Vorgabe deiner
  Abteilung.

Nur Personen mit Prüfrecht für eine Abteilung sehen dort Freigeben und
Änderungen anfordern.

### Profil

Dein Name, deine Matrix-ID, Abteilungen und wo du freigeben darfst;
**Sprache**; **Passwort ändern** für dein Matrix-Passwort; **Abmelden**.

### Personen (nur Owner)

Wenn du den Zugang deines Teams verwaltest, listet **Personen** alle auf
deinem Server.

- **Person hinzufügen**: Name, Benutzername (wird zu `@name:{{HOST}}`),
  Sprache, und pro Abteilung, ob die Person Mitglied ist und ob sie
  freigeben darf. Das Portal zeigt die Anmeldedaten einmal, mit
  **Kopieren**-Knöpfen und **Alles kopieren**; übergib sie persönlich oder
  telefonisch, nicht per E-Mail.
- **Ändern**: Abteilungen an- oder abwählen, Sprache setzen. Neue Räume
  werden sofort angeboten; Räume, zu denen die Person nicht mehr gehört,
  werden ihr entzogen.
- **Person entfernen**: nimmt jeden Raum und das Portal weg; das Konto wird
  endgültig geschlossen.

Jede Änderung dauert bis zu einer Minute. Du kannst nur Abteilungen
vergeben, die du siehst, und Freigabe nur dort, wo du freigeben darfst;
Owner und dein eigenes Konto ändert der Betreiber. Lade Personen nur hier
ein, nicht aus der Matrix-App: Einladungen aus der App werden wieder
zurückgezogen.

## Gut zu wissen

- Füge keine Passwörter, Kartennummern oder persönliche Daten anderer in
  Karten oder Chats ein, es sei denn, der Prozess deines Teams sieht es vor.
- Alles bleibt auf dem Server und im Netz deines Unternehmens; die
  Assistenten nutzen zum Denken ein externes KI-Modell, behandle Chats also
  wie E-Mails an einen Kollegen, nicht wie ein Tagebuch.
- Etwas fehlt oder stimmt nicht? Sag es der Person, die dein Konto
  eingerichtet hat.

## Was ist neu

- **2026-10-27 (abends)**: Portal, Anmeldenachrichten und diese Anleitung auf **Deutsch**: Die Sprache folgt deinem Browser, oben rechts stellst du sie um, unter Profil legst du sie für Anmeldelinks und Erinnerungen fest. Die Assistenten antworten in der Sprache, in der du schreibst.
- **2026-10-27 (nachmittags)**: Jeder Assistent kann eine **Website lesen** für sein Team: Adresse posten, nummerierten Vorschlag bekommen (Angebote und ideale Kunden für den Vertrieb, offene Stellen für HR), bestätigen oder ändern, und erst dann wird etwas gespeichert.
- **2026-10-27**: **Vertriebsdaten** im Raum Sales (Leads, Kontakte, Deals, Kontaktpunkte), Entwürfe für LinkedIn, Instagram, WhatsApp und E-Mail, die du sendest, ein konfigurierbarer Funnel und Ablehnungsgründe, eine dauerhafte Nicht-kontaktieren-Liste und eine Kachel **Funnel** auf dem Dashboard des Vertriebsteams.
- **2026-10-26 (nachmittags)**: Das **Dashboard** ist die Startseite des Portals: Ziele, Key Results, KPIs mit Trends, offene Arbeit und Wochenrückblicke deines Teams. Team-Owner legen sie dort fest; alle erfassen Werte.
- **2026-10-26 (spät)**: Die Portal-Anmeldung nimmt deinen einfachen Benutzernamen (`@name`); die vollständige Matrix-ID ist nicht mehr nötig.
- **2026-10-26 (nachts)**: **Swimlanes** pro Team auf dem Board (Owner legen sie auf dem Dashboard fest, verknüpft mit einem Ziel und einer KPI), Ziele und KPIs in ein anderes Team **verschieben**, die Liste **Alle Dateien** mit Filtern und Board-Filter mit **mehreren Werten** als Chips.
- **2026-10-26 (abends)**: Der Assistent schreibt jeden Montag einen **Wochenrückblick** zur Freigabe und erinnert den Raum freitags an fehlende Check-ins; Karten haben **Beteiligte** (Owner, Reviewer, Beobachter), können **auf ein Key Result einzahlen** und bekommen **einen Thread im Teamraum**, in dem ihre Ereignisse und deine Kommentare landen.
- **2026-10-26**: Text, den du im Portal eingibst, wird auf versteckte
  (unsichtbare) Zeichen geprüft, die Anweisungen für einen Assistenten
  tragen können, die niemand sieht; sie werden entfernt, und das Portal sagt
  es dir. Abteilungs-Digests enden jetzt mit den Kosten des Assistenten der
  letzten 7 Tage.
- **2026-10-25 (abends)**: HR nimmt ein ZIP mit Bewerbungen für eine Stelle
  auf einmal an.
- **2026-10-25 (nachmittags)**: der Raum **HR** mit Rekrutierungshilfe
  (Stellen, Personen und Lebensläufe, Shortlists, Interviewstufen); wie
  Threads in Matrix funktionieren.
- **2026-10-25**: diese Anleitung im Portal (**Hilfe**); Passwort im Portal
  ändern; Kopieren-Knöpfe für neue Konten; Owner verwalten Personen im
  Portal; Slash-Befehle für alle (siehe oben).
- **2026-10-24**: Matrix-Räume pro Abteilung, Portal-Anmeldung über Matrix,
  Zugang vom Telefon über HTTPS, Morgen-Digests in den Abteilungsräumen.
