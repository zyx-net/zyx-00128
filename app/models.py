from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Sample(db.Model):
    __tablename__ = 'samples'

    id = db.Column(db.Integer, primary_key=True)
    sample_code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    sample_type = db.Column(db.String(100))
    required_temp_zone = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False, default='REGISTERED')
    location_id = db.Column(db.Integer, db.ForeignKey('locations.id'), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    created_by = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    remark = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False)

    location = db.relationship('Location', backref='samples')
    audit_logs = db.relationship('AuditLog', backref='sample', lazy='dynamic', order_by='AuditLog.sequence')

    def to_dict(self):
        return {
            'id': self.id,
            'sample_code': self.sample_code,
            'name': self.name,
            'sample_type': self.sample_type,
            'required_temp_zone': self.required_temp_zone,
            'status': self.status,
            'location_id': self.location_id,
            'location_name': self.location.name if self.location else None,
            'version': self.version,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'remark': self.remark,
            'is_deleted': self.is_deleted
        }


class Location(db.Model):
    __tablename__ = 'locations'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    temp_zone = db.Column(db.String(50), nullable=False)
    capacity = db.Column(db.Integer, default=100)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'code': self.code,
            'name': self.name,
            'temp_zone': self.temp_zone,
            'capacity': self.capacity,
            'description': self.description,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'sample_count': len(self.samples) if self.samples else 0
        }


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.Integer, db.ForeignKey('samples.id'), nullable=False, index=True)
    sequence = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(50), nullable=False)
    from_status = db.Column(db.String(50))
    to_status = db.Column(db.String(50))
    from_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    to_location_id = db.Column(db.Integer, db.ForeignKey('locations.id'))
    operator = db.Column(db.String(100), nullable=False)
    operator_role = db.Column(db.String(100))
    reason = db.Column(db.Text)
    version = db.Column(db.Integer, nullable=False)
    remark = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    from_location = db.relationship('Location', foreign_keys=[from_location_id])
    to_location = db.relationship('Location', foreign_keys=[to_location_id])

    def to_dict(self):
        return {
            'id': self.id,
            'sample_id': self.sample_id,
            'sequence': self.sequence,
            'action': self.action,
            'from_status': self.from_status,
            'to_status': self.to_status,
            'from_location_id': self.from_location_id,
            'from_location_name': self.from_location.name if self.from_location else None,
            'to_location_id': self.to_location_id,
            'to_location_name': self.to_location.name if self.to_location else None,
            'operator': self.operator,
            'operator_role': self.operator_role,
            'reason': self.reason,
            'version': self.version,
            'remark': self.remark,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def to_csv_row(self):
        return [
            self.sequence,
            self.action,
            self.from_status or '',
            self.to_status or '',
            self.from_location.name if self.from_location else '',
            self.to_location.name if self.to_location else '',
            self.operator,
            self.operator_role or '',
            self.reason or '',
            self.version,
            self.remark or '',
            self.created_at.isoformat() if self.created_at else ''
        ]
