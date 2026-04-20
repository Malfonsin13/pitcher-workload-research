# server_version.py - retrieve and display database server version

import MySQLdb
import trajectory_drag

conn1 = MySQLdb.connect (host = "localhost",
    user = "root",
    passwd = "",
    db = "teamdata_2009_04")
conn2 = MySQLdb.connect (host = "localhost",
    user = "root",
    passwd = "",
    db = "teamdata_2009_04")
cursor1 = conn1.cursor ()
cursor2 = conn2.cursor ()
cursor2.execute ("DROP TABLE IF EXISTS hit_trajectory;")
cursor2.execute ("CREATE TABLE hit_trajectory (id int, distance float, time decimal(5,2));")
cursor1.execute ("SELECT id, hit_initial_speed, hit_vertical_angle, hit_z0 FROM hitballs;")
while (1):
    row = cursor1.fetchone ()
    if row == None:
        break
    a, b = trajectory_drag.hitball_func(row[1],row[2],row[3])
    cursor2.execute ("""
         INSERT INTO hit_trajectory (id, distance, time)
         VALUES ('%s', '%s', '%s');
       """, (row[0], a, b))
cursor1.close ()
conn1.close ()
cursor2.close ()
conn2.close ()
