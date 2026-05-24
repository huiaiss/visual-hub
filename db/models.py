import datetime
import uuid
from peewee import (
    SqliteDatabase, Model, CharField, TextField,
    IntegerField, DateTimeField, ForeignKeyField, BooleanField
)

db = SqliteDatabase(None, pragmas={"journal_mode": "wal"})


def _utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def _gen_id():
    return uuid.uuid4().hex[:12]


class BaseModel(Model):
    class Meta:
        database = db


class RegisteredUser(BaseModel):
    phone = CharField(max_length=11, unique=True)
    platform = CharField(max_length=64)
    category = CharField(max_length=64)
    name = CharField(max_length=256, default="")
    created_at = DateTimeField(default=_utcnow)

    def save(self, *args, **kwargs):
        import re
        if not re.match(r"^1[3-9]\d{9}$", self.phone):
            raise ValueError(f"Invalid phone number: {self.phone}")
        return super().save(*args, **kwargs)


class GeneratedPlan(BaseModel):
    """Persisted shooting plan with all variants."""
    plan_id = CharField(max_length=32, unique=True, default=_gen_id)
    industry = CharField(max_length=32)
    script_type = CharField(max_length=16)
    product_analysis = TextField()  # JSON: structured product analysis from creative_engine
    creative_brief = TextField(default="")  # JSON: creative brief from creative_engine
    extra_info = TextField(default="")
    image_paths = TextField()  # JSON array
    variant_count = IntegerField(default=1)
    plans_json = TextField()   # Full JSON of all variants
    rating = IntegerField(null=True, default=None)  # -1=差 0=一般 1=好
    performance_note = TextField(default="")  # 用户对效果的备注
    created_at = DateTimeField(default=_utcnow)


class CreativeBrief(BaseModel):
    """Standalone creative brief — can exist without generated plans."""
    brief_id = CharField(max_length=32, unique=True, default=_gen_id)
    industry = CharField(max_length=32)
    product_name = CharField(max_length=128, default="")
    product_analysis = TextField()  # JSON: structured product analysis
    creative_brief = TextField()  # JSON: concept/scenes/colors/model/BGM
    image_paths = TextField()  # JSON array of input image paths
    scene_images = TextField(default="[]")  # JSON array of generated scene background paths
    status = CharField(max_length=16, default="draft")  # draft/ready/generating/complete
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)


class BatchJob(BaseModel):
    """Batch generation job — multi-scene × multi-angle × multi-platform."""
    job_id = CharField(max_length=32, unique=True, default=_gen_id)
    brief = ForeignKeyField(CreativeBrief, backref="jobs", null=True, on_delete="SET NULL")
    status = CharField(max_length=16, default="pending")  # pending/processing/completed/failed/cancelled
    progress = IntegerField(default=0)  # 0-100
    message = CharField(max_length=256, default="")
    input_config = TextField()  # JSON: {image_paths, industry, script_type, variant_count, scenes[], platforms[], colors[]}
    output_summary = TextField(default="{}")  # JSON: {total_images, scenes, platforms, errors[]}
    output_files = TextField(default="[]")  # JSON array of output file paths
    created_at = DateTimeField(default=_utcnow)
    updated_at = DateTimeField(default=_utcnow)
    completed_at = DateTimeField(null=True, default=None)


