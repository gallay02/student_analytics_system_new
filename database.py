import sqlite3
import pandas as pd
import json
import os
import hashlib
from datetime import datetime
import numpy as np
from config import DB_BASE_PATH

def get_user_db_path(user_id):
    """获取用户专属数据库路径"""
    user_folder = os.path.join(DB_BASE_PATH, f"user_{user_id}")
    os.makedirs(user_folder, exist_ok=True)
    return os.path.join(user_folder, "student_analytics.db")

def init_database(db_path):
    """初始化数据库（传入具体路径）"""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 评价维度配置表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluation_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name TEXT NOT NULL,
            subject TEXT NOT NULL,
            dimensions TEXT NOT NULL,
            description TEXT,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 学生表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            class_name TEXT,
            subject TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 检查并添加缺失的 class_id 列
    cursor.execute("PRAGMA table_info(students)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'class_id' not in columns:
        cursor.execute('ALTER TABLE students ADD COLUMN class_id INTEGER')
    
    # 班级表（确保存在）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS classes (
            class_id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_name TEXT NOT NULL,
            subject TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 评价记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS evaluations (
            eval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            lesson_id TEXT,
            lesson_name TEXT,
            subject TEXT,
            template_id INTEGER,
            eval_date TIMESTAMP,
            evaluator TEXT,
            scores_json TEXT NOT NULL,
            total_score REAL,
            comments TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    ''')
    
    # 检查并添加缺失的 class_id 列到evaluations表
    cursor.execute("PRAGMA table_info(evaluations)")
    eval_columns = [col[1] for col in cursor.fetchall()]
    if 'class_id' not in eval_columns:
        cursor.execute('ALTER TABLE evaluations ADD COLUMN class_id INTEGER')
    
    # 确保 custom_subjects 表存在（兼容旧数据库）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_subjects (
            subject_id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 学情快照表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS learning_status (
            status_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            lesson_id TEXT,
            subject TEXT,
            pre_lesson_status TEXT,
            risk_level TEXT,
            suggested_focus TEXT,
            generated_at TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    ''')
    
    # 阶段总评表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS phase_evaluations (
            phase_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            subject TEXT,
            phase_name TEXT,
            start_date TIMESTAMP,
            end_date TIMESTAMP,
            overall_score REAL,
            overall_level TEXT,
            strength_areas TEXT,
            weakness_areas TEXT,
            development_suggestions TEXT,
            ai_report TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(student_id)
        )
    ''')
    
    # 用户账户表（用于登录验证）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_accounts (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# 全局变量存储当前用户数据库路径
_current_db_path = None

def set_current_user(user_id):
    """设置当前用户，切换数据库"""
    global _current_db_path
    _current_db_path = get_user_db_path(user_id)
    init_database(_current_db_path)
    return _current_db_path

def get_db_path():
    """获取当前数据库路径"""
    global _current_db_path
    if _current_db_path is None:
        raise ValueError("未设置当前用户，请先调用 set_current_user()")
    return _current_db_path

# 以下所有函数都需要使用 get_db_path() 替代原来的 DB_PATH

def import_students(df, subject, class_id=None):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    try:
        for _, row in df.iterrows():
            student_id = str(row.get('学号', '')).strip()
            name = str(row.get('姓名', '')).strip()
            class_name = str(row.get('班级', '')).strip()
            
            if not student_id or not name:
                continue
            
            cursor.execute('''
                INSERT OR REPLACE INTO students (student_id, name, class_name, class_id, subject)
                VALUES (?, ?, ?, ?, ?)
            ''', (student_id, name, class_name, class_id, subject))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()

def save_template(template_name, subject, dimensions, description="", created_by=""):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO evaluation_templates (template_name, subject, dimensions, description, created_by)
        VALUES (?, ?, ?, ?, ?)
    ''', (template_name, subject, json.dumps(dimensions, ensure_ascii=False), description, created_by))
    conn.commit()
    template_id = cursor.lastrowid
    conn.close()
    return template_id

def get_templates(subject=None):
    conn = sqlite3.connect(get_db_path())
    query = "SELECT * FROM evaluation_templates"
    params = []
    if subject:
        query += " WHERE subject = ?"
        params.append(subject)
    query += " ORDER BY created_at DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty:
        df['dimensions'] = df['dimensions'].apply(json.loads)
    return df

def delete_template(template_id):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    # 检查是否有评价数据使用此模板
    cursor.execute("SELECT COUNT(*) FROM evaluations WHERE template_id = ?", (template_id,))
    count = cursor.fetchone()[0]
    
    if count > 0:
        conn.close()
        return False, f"该模板已被 {count} 条评价数据使用，无法删除"
    
    # 删除模板
    cursor.execute("DELETE FROM evaluation_templates WHERE template_id = ?", (template_id,))
    conn.commit()
    conn.close()
    return True, "模板删除成功"


def get_template(template_id):
    conn = sqlite3.connect(get_db_path())
    df = pd.read_sql_query("SELECT * FROM evaluation_templates WHERE template_id = ?", 
                           conn, params=[template_id])
    conn.close()
    if not df.empty:
        result = df.iloc[0].to_dict()
        result['dimensions'] = json.loads(result['dimensions'])
        return result
    return None

def save_evaluation(eval_data):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    
    # 确保 evaluations 表有 class_id 列
    cursor.execute("PRAGMA table_info(evaluations)")
    eval_columns = [col[1] for col in cursor.fetchall()]
    if 'class_id' not in eval_columns:
        cursor.execute('ALTER TABLE evaluations ADD COLUMN class_id INTEGER')
        conn.commit()  # 立即提交 ALTER TABLE
    
    cursor.execute('''
        INSERT INTO evaluations 
        (student_id, lesson_id, lesson_name, subject, template_id, eval_date, evaluator, scores_json, total_score, comments, class_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        eval_data['student_id'],
        eval_data['lesson_id'],
        eval_data['lesson_name'],
        eval_data['subject'],
        eval_data.get('template_id'),
        eval_data['eval_date'],
        eval_data['evaluator'],
        json.dumps(eval_data['scores'], ensure_ascii=False),
        eval_data['total_score'],
        eval_data.get('comments', ''),
        eval_data.get('class_id')  # 添加班级ID
    ))
    conn.commit()
    eval_id = cursor.lastrowid
    conn.close()
    return eval_id

def get_student_evaluations(student_id, subject=None, class_id=None):
    conn = sqlite3.connect(get_db_path())
    query = "SELECT * FROM evaluations WHERE student_id = ?"
    params = [student_id]
    if subject:
        query += " AND subject = ?"
        params.append(subject)
    if class_id is not None:
        query += " AND class_id = ?"
        params.append(class_id)
    query += " ORDER BY eval_date"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty and 'scores_json' in df.columns:
        scores_df = df['scores_json'].apply(lambda x: json.loads(x) if pd.notna(x) else {}).apply(pd.Series)
        scores_df = scores_df.apply(pd.to_numeric, errors='coerce').fillna(np.nan)
        scores_df = scores_df.apply(lambda x: x.where((x >= 0) & (x <= 100), np.nan))
        df = pd.concat([df.drop('scores_json', axis=1), scores_df], axis=1)
    return df

def get_class_evaluations(lesson_id=None, subject=None, template_id=None, class_id=None):
    conn = sqlite3.connect(get_db_path())
    query = "SELECT e.*, s.name FROM evaluations e LEFT JOIN students s ON e.student_id = s.student_id WHERE 1=1"
    params = []
    if lesson_id:
        query += " AND e.lesson_id = ?"
        params.append(lesson_id)
    if subject:
        query += " AND e.subject = ?"
        params.append(subject)
    if template_id:
        query += " AND e.template_id = ?"
        params.append(template_id)
    if class_id is not None:
        query += " AND e.class_id = ?"
        params.append(class_id)
    query += " ORDER BY e.eval_date"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty and 'scores_json' in df.columns:
        scores_df = df['scores_json'].apply(lambda x: json.loads(x) if pd.notna(x) else {}).apply(pd.Series)
        scores_df = scores_df.apply(pd.to_numeric, errors='coerce').fillna(np.nan)
        scores_df = scores_df.apply(lambda x: x.where((x >= 0) & (x <= 100), np.nan))
        df = pd.concat([df.drop('scores_json', axis=1), scores_df], axis=1)
    return df

def delete_evaluation(eval_id):
    """删除指定的评价记录"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM evaluations WHERE eval_id = ?', (eval_id,))
    conn.commit()
    rowcount = cursor.rowcount
    conn.close()
    return rowcount > 0

def delete_evaluations_by_lesson(lesson_id):
    """删除指定课时的所有评价记录"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM evaluations WHERE lesson_id = ?', (lesson_id,))
    conn.commit()
    rowcount = cursor.rowcount
    conn.close()
    return rowcount

def delete_evaluations_by_class(class_id):
    """删除指定班级的所有评价记录"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM evaluations WHERE class_id = ?', (class_id,))
    conn.commit()
    rowcount = cursor.rowcount
    conn.close()
    return rowcount

def save_learning_status(status_data):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO learning_status 
        (student_id, lesson_id, subject, pre_lesson_status, risk_level, suggested_focus, generated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        status_data['student_id'],
        status_data['lesson_id'],
        status_data['subject'],
        status_data['pre_lesson_status'],
        status_data['risk_level'],
        status_data['suggested_focus'],
        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ))
    conn.commit()
    conn.close()

def save_phase_evaluation(phase_data):
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO phase_evaluations 
        (student_id, subject, phase_name, start_date, end_date, overall_score, 
         overall_level, strength_areas, weakness_areas, development_suggestions, ai_report)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        phase_data['student_id'],
        phase_data['subject'],
        phase_data['phase_name'],
        phase_data['start_date'],
        phase_data['end_date'],
        phase_data['overall_score'],
        phase_data['overall_level'],
        phase_data['strength_areas'],
        phase_data['weakness_areas'],
        phase_data['development_suggestions'],
        phase_data['ai_report']
    ))
    conn.commit()
    conn.close()

# 自定义科目管理
def save_custom_subject(subject_name):
    """保存用户自定义科目"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO custom_subjects (subject_name) VALUES (?)', (subject_name,))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False  # 已存在
    conn.close()
    return success

def get_custom_subjects():
    """获取用户自定义科目列表"""
    conn = sqlite3.connect(get_db_path())
    df = pd.read_sql_query("SELECT subject_name FROM custom_subjects ORDER BY created_at", conn)
    conn.close()
    return df['subject_name'].tolist() if not df.empty else []

def delete_custom_subject(subject_name):
    """删除用户自定义科目"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM custom_subjects WHERE subject_name = ?', (subject_name,))
    conn.commit()
    conn.close()

# ============ 用户认证相关函数 ============
def register_user(username, password):
    """注册新用户"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    try:
        cursor.execute('INSERT INTO user_accounts (username, password_hash) VALUES (?, ?)', 
                      (username, password_hash))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False  # 用户名已存在
    conn.close()
    return success

def authenticate_user(username, password):
    """验证用户登录"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute('SELECT * FROM user_accounts WHERE username = ? AND password_hash = ?', 
                  (username, password_hash))
    user = cursor.fetchone()
    conn.close()
    return user is not None

def user_exists(username):
    """检查用户名是否存在"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM user_accounts WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    return user is not None

# ============ 班级管理相关函数 ============
def save_class(class_name, subject):
    """保存班级"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO classes (class_name, subject) VALUES (?, ?)', 
                      (class_name, subject))
        conn.commit()
        class_id = cursor.lastrowid
        success = True
    except sqlite3.IntegrityError:
        success = False
        class_id = None
    conn.close()
    return success, class_id

def get_classes(subject=None):
    """获取班级列表"""
    conn = sqlite3.connect(get_db_path())
    query = "SELECT * FROM classes"
    params = []
    if subject:
        query += " WHERE subject = ?"
        params.append(subject)
    query += " ORDER BY created_at"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

def get_class_by_id(class_id):
    """根据ID获取班级信息"""
    conn = sqlite3.connect(get_db_path())
    df = pd.read_sql_query("SELECT * FROM classes WHERE class_id = ?", conn, params=[class_id])
    conn.close()
    if not df.empty:
        return df.iloc[0].to_dict()
    return None

def delete_class(class_id):
    """删除班级"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM classes WHERE class_id = ?', (class_id,))
    conn.commit()
    conn.close()

def get_students_by_class(class_id):
    """根据班级ID获取学生列表"""
    conn = sqlite3.connect(get_db_path())
    df = pd.read_sql_query("SELECT * FROM students WHERE class_id = ?", conn, params=[class_id])
    conn.close()
    return df

def delete_students_by_class(class_id):
    """删除指定班级的所有学生"""
    conn = sqlite3.connect(get_db_path())
    cursor = conn.cursor()
    cursor.execute('DELETE FROM students WHERE class_id = ?', (class_id,))
    conn.commit()
    conn.close()