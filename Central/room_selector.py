import sqlite3


class RoomSelector:
    def __init__(self, db_path="/app/data/classroom_data.db"):
        self.db_path = db_path.strip()

    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
        return conn

    def is_room_available(self, conn, room_id, req_start_date, req_end_date, req_start_time, req_end_time, req_days, exclude_schedule_id=None):
        if not req_start_date or not req_end_date or not req_start_time or not req_end_time:
            return True
            
        query = 'SELECT id, start_time, end_time, days FROM course_schedule WHERE room_id = ?'
        params = [room_id]
        if exclude_schedule_id:
            query += ' AND id != ?'
            params.append(exclude_schedule_id)
            
        existing_schedules = conn.execute(query, params).fetchall()
        req_days_set = set(d.strip().lower() for d in (req_days or '').split())

        for row in existing_schedules:
            ex_start_dt = str(row['start_time'])
            ex_end_dt = str(row['end_time'])
            
            
            ex_start_date, ex_start_time_val = ex_start_dt.split(' ')[0], ex_start_dt.split(' ')[1][:5]
            ex_end_date, ex_end_time_val = ex_end_dt.split(' ')[0], ex_end_dt.split(' ')[1][:5]
            ex_days = str(row['days'] or '')
            
            # Semester-long date overlap check
            if req_start_date <= ex_end_date and req_end_date >= ex_start_date:
                # Daily time overlap check
                if req_start_time < ex_end_time_val and req_end_time > ex_start_time_val:
                    ex_days_set = set(d.strip().lower() for d in ex_days.split())
                    if not req_days_set or not ex_days_set or not req_days_set.isdisjoint(ex_days_set):
                        return False
        return True

    def find_best_room(self, student_count, requirements, req_start_date=None, req_end_date=None, req_start_time=None, req_end_time=None, req_days=None, exclude_schedule_id=None):
        conn = self._conn()
        try:
            allowed = {"has_projector", "has_pcs", "has_ventilation"}
            # Ensure table prefix matches metadata table
            #clauses = [f"{r}=1" for r in requirements if r in allowed]
            clauses = [f"m.{r}=1" for r in requirements if r in allowed]
            
            # Calculates historical manual command count per room
            q = """
                SELECT m.*, 
                       (SELECT COUNT(*) FROM control_logs cl 
                        WHERE cl.room_id = m.room_id 
                        AND cl.timestamp > datetime('now', '-30 days')) as manual_command_count
                FROM classroom_metadata m 
                WHERE m.capacity >= ?
            """
            
            params = [student_count]
            if clauses: 
                q += " AND " + " AND ".join(clauses)
                
                
            # q = "SELECT * FROM classroom_metadata WHERE capacity >= ?"
            # params = [student_count]
            # if clauses: q += " AND " + " AND ".join(clauses)

            rooms = [dict(r) for r in conn.execute(q, params).fetchall()]
            if not rooms: return None
            
            # Filter out rooms with physical scheduling conflicts
            available_rooms = []
            for r in rooms:
                if self.is_room_available(conn, r['room_id'], req_start_date, req_end_date, req_start_time, req_end_time, req_days, exclude_schedule_id):
                    available_rooms.append(r)
                    
            if not available_rooms: return None

            # SCORING FUNCTION
            return max(available_rooms,
                       key=lambda r: (
                           # The scoring function prioritizes:
                           # 1. High energy efficiency (up to 100 points)
                           # 2. Lower thermal loss (penalty, max ~10 points for a rate of 1.0)
                           # 3. Less wasted space (mild penalty for excess capacity)
                               # 1. Base Score: Efficiency (0 to 100)
                               (r['avg_efficiency_score'] or 50.0) -
                               # 2. Capacity Penalty: Mildly penalize wasted space
                               ((r['capacity'] - student_count) * 0.1) - 
                               # 3. Thermal Loss Penalty: Scaled to the 0.0 - 1.0 dynamic range
                               # A loss rate of 1.0 (leaky) results in a 15-point penalty
                               ((r['thermal_loss_rate'] or 0.5) * 15.0) -
                               
                               # 4. Manual Mode Penalty:
                               # Deduct 1 point for every 5 manual commands in the last 30 days
                               ((r.get('manual_command_count', 0) / 5.0))
                       ))
        finally:
            conn.close()