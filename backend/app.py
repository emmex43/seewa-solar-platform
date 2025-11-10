from flask import Flask, jsonify, request, render_template, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import math
from datetime import datetime
import os
import numpy as np
import logging
from typing import Dict, List, Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../frontend/static",
            template_folder="../frontend/templates")
CORS(app)

app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///seewa.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = "2025etgdhdhhjjdjjsakoyddhhrttsgg"

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

# User Model


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='user')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# Project Model


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_name = db.Column(db.String(100))
    location = db.Column(db.String(100))
    capacity_kw = db.Column(db.Float)
    cost_usd = db.Column(db.Float)
    status = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "project_name": self.project_name,
            "location": self.location,
            "capacity_kw": self.capacity_kw,
            "cost_usd": self.cost_usd,
            "status": self.status,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

# Appliance Model


class Appliance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    power_watt = db.Column(db.Integer, nullable=False)
    hours_per_day = db.Column(db.Float, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey(
        'user.id'), nullable=True)  # Allow null for existing data
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "power_watt": self.power_watt,
            "hours_per_day": self.hours_per_day,
            "daily_energy_kwh": round((self.power_watt * self.hours_per_day) / 1000, 2),
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

# Analytics Model


class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    data = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Enhanced Nigeria Solar Data - More cities and seasonal data
NIGERIA_SOLAR_DATA = {
    'lagos': {'lat': 6.5244, 'lng': 3.3792, 'irradiance': 4.8, 'region': 'south'},
    'abuja': {'lat': 9.0579, 'lng': 7.4951, 'irradiance': 5.2, 'region': 'middle_belt'},
    'kano': {'lat': 12.0022, 'lng': 8.5920, 'irradiance': 5.5, 'region': 'north'},
    'ibadan': {'lat': 7.3776, 'lng': 3.9470, 'irradiance': 4.9, 'region': 'south'},
    'port harcourt': {'lat': 4.8156, 'lng': 7.0498, 'irradiance': 4.5, 'region': 'south'},
    'benin city': {'lat': 6.3350, 'lng': 5.6037, 'irradiance': 4.7, 'region': 'south'},
    'kaduna': {'lat': 10.5105, 'lng': 7.4165, 'irradiance': 5.3, 'region': 'north'},
    'maiduguri': {'lat': 11.8333, 'lng': 13.1500, 'irradiance': 5.6, 'region': 'north'},
    'ilorin': {'lat': 8.5000, 'lng': 4.5500, 'irradiance': 5.1, 'region': 'middle_belt'},
    'enugu': {'lat': 6.4500, 'lng': 7.5000, 'irradiance': 4.8, 'region': 'south'},
    'sokoto': {'lat': 13.0667, 'lng': 5.2333, 'irradiance': 5.7, 'region': 'north'}
}

# Monthly irradiance factors for Nigeria (seasonal variations)
NIGERIA_MONTHLY_FACTORS = {
    1: 1.10, 2: 1.12, 3: 1.08, 4: 0.95, 5: 0.85, 6: 0.80,
    7: 0.82, 8: 0.85, 9: 0.90, 10: 1.00, 11: 1.05, 12: 1.08
}

# Enhanced Nigeria-specific data
NIGERIA_ELECTRICITY_COST = 0.15      # USD/kWh (average)
NIGERIA_ELECTRICITY_COST_NAIRA = 225  # ₦/kWh (approx 1500 ₦/$)
NIGERIA_EMISSION_FACTOR = 0.61       # kg CO2/kWh (Nigeria grid)
# kWh/year (more accurate Nigerian average)
AVERAGE_HOME_CONSUMPTION = 2400


class SolarEstimator:
    def __init__(self):
        # More granular loss factors
        self.loss_factors = {
            'soiling': 0.97,           # Dust, dirt (Nigeria-specific)
            'shading': 0.98,           # Partial shading losses
            'mismatch': 0.98,          # Panel manufacturing variations
            'wiring_dc': 0.98,         # DC wiring losses
            'wiring_ac': 0.99,         # AC wiring losses
            'inverter': 0.96,          # Inverter efficiency
            'age': 0.995,              # First year degradation
            'availability': 0.99,      # System downtime
        }

        # Nigeria regional adjustments
        self.regional_adjustments = {
            'north': {'soiling': 0.94, 'temperature': 0.92},
            'south': {'soiling': 0.96, 'temperature': 0.94},
            'middle_belt': {'soiling': 0.95, 'temperature': 0.93},
            'lagos': {'soiling': 0.97, 'temperature': 0.95}
        }

    @staticmethod
    def get_nigerian_solar_irradiance(lat, lon):
        """Get solar irradiance data with NASA API fallback to cached Nigerian data"""
        # First try NASA API
        nasa_data = SolarEstimator._try_nasa_api(lat, lon)
        if nasa_data is not None:
            return nasa_data

        # Fallback to cached Nigerian data
        return SolarEstimator._get_cached_nigerian_irradiance(lat, lon)

    @staticmethod
    def _try_nasa_api(lat, lon):
        """Try to get data from NASA API with proper error handling"""
        try:
            params = {
                'parameters': 'ALLSKY_SFC_SW_DWN',
                'community': 'RE',
                'longitude': lon,
                'latitude': lat,
                'start': '2020',
                'end': '2025',
                'format': 'JSON'
            }

            response = requests.get(
                "https://power.larc.nasa.gov/api/system/application/run.json",
                params=params,
                timeout=5  # Shorter timeout
            )

            if response.status_code == 200:
                data = response.json()
                irradiance_data = data['properties']['parameter']['ALLSKY_SFC_SW_DWN']
                values = [v for v in irradiance_data.values() if v is not None]

                if values:
                    irradiance = sum(values) / len(values)
                    logger.info(
                        f"✅ NASA API Success: {irradiance} kWh/m²/day for ({lat}, {lon})")
                    return irradiance

        except requests.exceptions.Timeout:
            logger.warning("⚠️ NASA API timeout - using cached data")
        except requests.exceptions.ConnectionError:
            logger.warning("⚠️ NASA API connection error - using cached data")
        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ NASA API error: {e} - using cached data")
        except Exception as e:
            logger.warning(
                f"⚠️ NASA API parsing error: {e} - using cached data")

        return None

    @staticmethod
    def _get_cached_nigerian_irradiance(lat, lon):
        """Get irradiance from cached Nigerian data based on proximity"""
        # Find the closest Nigerian city
        closest_city = None
        min_distance = float('inf')

        for city_name, city_data in NIGERIA_SOLAR_DATA.items():
            distance = math.sqrt(
                (lat - city_data['lat'])**2 + (lon - city_data['lng'])**2)
            if distance < min_distance:
                min_distance = distance
                closest_city = city_name

        if closest_city:
            irradiance = NIGERIA_SOLAR_DATA[closest_city]['irradiance']
            logger.info(
                f"📍 Using cached data for {closest_city.title()}: {irradiance} kWh/m²/day")
            return irradiance

        # Default fallback - Nigeria average
        logger.info("📍 Using Nigeria average: 5.0 kWh/m²/day")
        return 5.0

    def calculate_total_losses(self, region='middle_belt', panel_tilt=15, has_battery=False):
        """Calculate comprehensive system losses"""
        # Start with base losses
        total_loss = np.prod(list(self.loss_factors.values()))

        # Apply regional adjustments
        region_data = self.regional_adjustments.get(region, {})
        total_loss *= region_data.get('soiling', 1.0)
        total_loss *= region_data.get('temperature', 1.0)

        # Tilt factor adjustment
        tilt_factor = self.calculate_tilt_factor(panel_tilt)
        total_loss *= tilt_factor

        # Battery system losses if applicable
        if has_battery:
            total_loss *= 0.92  # Battery round-trip efficiency

        return total_loss

    def calculate_tilt_factor(self, tilt_angle, optimal_tilt=15):
        """Calculate performance factor based on tilt angle"""
        tilt_diff = abs(tilt_angle - optimal_tilt)
        # ~0.3% loss per degree off optimal
        return max(0.85, 1 - (tilt_diff * 0.003))

    def calculate_solar_potential(self, irradiance, area, efficiency=0.18,
                                  region='middle_belt', panel_tilt=15, has_battery=False):
        """Calculate solar energy potential with enhanced factors"""

        total_system_loss = self.calculate_total_losses(
            region, panel_tilt, has_battery)

        daily_energy = irradiance * area * efficiency * total_system_loss
        annual_energy = daily_energy * 365

        # Apply seasonal adjustment
        current_month = datetime.now().month
        seasonal_factor = NIGERIA_MONTHLY_FACTORS.get(current_month, 1.0)
        adjusted_annual_energy = annual_energy * seasonal_factor

        return adjusted_annual_energy

    def calculate_advanced_benefits(self, energy_kwh, system_cost=0, include_financial=False):
        """Calculate comprehensive benefits with financial analysis"""
        benefits = self.calculate_nigerian_benefits(energy_kwh)

        if include_financial and system_cost > 0:
            financials = self.calculate_financial_analysis(
                energy_kwh, system_cost)
            benefits.update(financials)

        return benefits

    def calculate_financial_analysis(self, annual_energy_kwh, system_cost):
        """Calculate financial metrics"""
        annual_savings = annual_energy_kwh * NIGERIA_ELECTRICITY_COST
        simple_payback = system_cost / annual_savings if annual_savings > 0 else 0

        # 25-year analysis with degradation
        total_25yr_energy = 0
        degradation_rate = 0.005  # 0.5% per year

        for year in range(1, 26):
            year_energy = annual_energy_kwh * \
                ((1 - degradation_rate) ** (year - 1))
            total_25yr_energy += year_energy

        total_25yr_savings = total_25yr_energy * NIGERIA_ELECTRICITY_COST
        roi_percentage = ((total_25yr_savings - system_cost) /
                          system_cost) * 100 if system_cost > 0 else 0

        return {
            'simple_payback_years': round(simple_payback, 1),
            'total_25year_savings_usd': round(total_25yr_savings),
            'return_on_investment_percent': round(roi_percentage, 1),
            'system_cost_usd': system_cost
        }

    @staticmethod
    def calculate_nigerian_benefits(energy_kwh):
        """Calculate benefits specific to Nigeria"""
        carbon_offset_tons = (energy_kwh * NIGERIA_EMISSION_FACTOR) / 1000
        annual_savings_usd = energy_kwh * NIGERIA_ELECTRICITY_COST
        annual_savings_naira = energy_kwh * NIGERIA_ELECTRICITY_COST_NAIRA
        equivalent_homes = energy_kwh / AVERAGE_HOME_CONSUMPTION

        # More accurate tree calculation
        equivalent_trees = carbon_offset_tons / 0.02177

        return {
            'carbon_offset_tons': round(carbon_offset_tons, 1),
            'annual_savings_usd': round(annual_savings_usd),
            'annual_savings_naira': round(annual_savings_naira),
            'equivalent_homes': round(equivalent_homes, 1),
            'equivalent_trees': round(equivalent_trees)
        }

    def estimate_panel_count(self, area, panel_watts=450):
        """More accurate panel estimation"""
        panel_area_sq_m = 1.8 * 1.0  # Typical 450W panel dimensions
        usable_area = area * 0.85    # Account for spacing, gaps

        estimated_panels = math.floor(usable_area / panel_area_sq_m)
        system_size_kw = (estimated_panels * panel_watts) / 1000

        return {
            'estimated_panels': estimated_panels,
            'system_size_kw': round(system_size_kw, 1),
            'panel_watts': panel_watts,
            'coverage_ratio': round(usable_area / area, 2)
        }


# Initialize the enhanced solar estimator
solar_estimator = SolarEstimator()


def log_analytics(event_type, user_id=None, data=None):
    analytics = Analytics(
        event_type=event_type,
        user_id=user_id,
        data=data
    )
    db.session.add(analytics)
    db.session.commit()

# Authentication Routes


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            log_analytics('user_login', user.id)
            return redirect(url_for('home'))
        else:
            flash('Invalid username or password')

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "POST":
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        elif User.query.filter_by(email=email).first():
            flash('Email already exists')
        else:
            user = User(username=username, email=email)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()

            login_user(user)
            log_analytics('user_registration', user.id)
            return redirect(url_for('home'))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    log_analytics('user_logout', current_user.id)
    logout_user()
    return redirect(url_for('home'))

# Basic Routes


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/projects")
@login_required
def projects_page():
    return render_template("projects.html")


@app.route("/calculator")
def calculator_page():
    return render_template("calculator.html")


@app.route("/appliances")
@login_required
def appliances_page():
    return render_template("appliances.html")


@app.route("/analytics")
@login_required
def analytics_page():
    return render_template("analytics.html")

# PROJECTS API ENDPOINTS


@app.route("/api/projects", methods=["GET"])
@login_required
def get_projects():
    projects = Project.query.filter_by(user_id=current_user.id).all()
    return jsonify([p.to_dict() for p in projects])


@app.route("/api/projects", methods=["POST"])
@login_required
def add_project():
    data = request.json
    new_project = Project(**data)
    new_project.user_id = current_user.id
    db.session.add(new_project)
    db.session.commit()

    log_analytics('project_created', current_user.id,
                  f"Project: {data.get('project_name')}")
    return jsonify(new_project.to_dict())


@app.route("/api/projects/<int:id>", methods=["DELETE"])
@login_required
def delete_project(id):
    project = Project.query.filter_by(
        id=id, user_id=current_user.id).first_or_404()
    db.session.delete(project)
    db.session.commit()

    log_analytics('project_deleted', current_user.id, f"Project ID: {id}")
    return jsonify({"message": "Project deleted"})

# APPLIANCES API ENDPOINTS


@app.route("/api/appliances", methods=["GET"])
@login_required
def get_appliances():
    appliances = Appliance.query.filter_by(user_id=current_user.id).all()
    return jsonify([a.to_dict() for a in appliances])


@app.route("/api/appliances", methods=["POST"])
@login_required
def add_appliance():
    data = request.json
    new_appliance = Appliance(**data)
    new_appliance.user_id = current_user.id
    db.session.add(new_appliance)
    db.session.commit()

    log_analytics('appliance_added', current_user.id,
                  f"Appliance: {data.get('name')}")
    return jsonify(new_appliance.to_dict())


@app.route("/api/appliances/<int:id>", methods=["DELETE"])
@login_required
def delete_appliance(id):
    appliance = Appliance.query.filter_by(
        id=id, user_id=current_user.id).first_or_404()
    db.session.delete(appliance)
    db.session.commit()

    log_analytics('appliance_deleted', current_user.id, f"Appliance ID: {id}")
    return jsonify({"message": "Appliance deleted"})

# SOLAR ESTIMATION API ENDPOINTS


@app.route("/api/solar-estimate", methods=["POST"])
def solar_estimate():
    """Enhanced solar estimation endpoint for Nigerian locations"""
    try:
        data = request.json
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        area = float(data.get('area', 20))
        efficiency = float(data.get('efficiency', 0.18))
        panel_tilt = float(data.get('panel_tilt', 15))
        region = data.get('region', 'middle_belt')
        has_battery = data.get('has_battery', False)
        system_cost = float(data.get('system_cost', 0))

        # Get solar data (with fallback)
        irradiance = solar_estimator.get_nigerian_solar_irradiance(lat, lng)
        annual_energy = solar_estimator.calculate_solar_potential(
            irradiance, area, efficiency, region, panel_tilt, has_battery
        )

        # Calculate benefits with optional financial analysis
        include_financial = system_cost > 0
        benefits = solar_estimator.calculate_advanced_benefits(
            annual_energy, system_cost, include_financial
        )

        # Enhanced panel estimation
        panel_estimation = solar_estimator.estimate_panel_count(area)

        # Determine data source for the response
        data_source = "nasa_api" if SolarEstimator._try_nasa_api(
            lat, lng) is not None else "cached_data"

        response = {
            'success': True,
            'data_source': data_source,
            'location': {'lat': lat, 'lng': lng, 'region': region},
            'solar_data': {
                'daily_irradiance': round(irradiance, 2),
                'annual_energy_kwh': round(annual_energy),
                'monthly_energy_kwh': round(annual_energy / 12),
                'system_performance_ratio': round(solar_estimator.calculate_total_losses(region, panel_tilt, has_battery), 3)
            },
            'benefits': benefits,
            'system_size': panel_estimation,
            'calculation_parameters': {
                'panel_tilt': panel_tilt,
                'efficiency': efficiency,
                'has_battery': has_battery,
                'area_sq_m': area
            }
        }

        if current_user.is_authenticated:
            log_analytics('solar_calculation', current_user.id,
                          f"Location: {lat},{lng}, Area: {area}m², Region: {region}")

        return jsonify(response)

    except Exception as e:
        logger.error(f"Solar estimation error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
# ANALYTICS API ENDPOINTS


@app.route("/api/analytics/dashboard")
@login_required
def get_analytics_dashboard():
    user_calculations = Analytics.query.filter_by(
        user_id=current_user.id,
        event_type='solar_calculation'
    ).count()

    user_projects = Project.query.filter_by(user_id=current_user.id).count()
    user_appliances = Appliance.query.filter_by(
        user_id=current_user.id).count()

    recent_activity = Analytics.query.filter_by(user_id=current_user.id)\
        .order_by(Analytics.created_at.desc())\
        .limit(10)\
        .all()

    activity_data = []
    for activity in recent_activity:
        activity_data.append({
            'event_type': activity.event_type,
            'created_at': activity.created_at.isoformat(),
            'data': activity.data
        })

    return jsonify({
        'user_stats': {
            'solar_calculations': user_calculations,
            'projects_created': user_projects,
            'appliances_tracked': user_appliances
        },
        'recent_activity': activity_data
    })


@app.route("/api/nigerian-cities")
def nigerian_cities():
    cities = [
        {'name': 'Lagos', 'lat': 6.5244, 'lng': 3.3792},
        {'name': 'Abuja', 'lat': 9.0579, 'lng': 7.4951},
        {'name': 'Kano', 'lat': 12.0022, 'lng': 8.5920},
        {'name': 'Ibadan', 'lat': 7.3776, 'lng': 3.9470},
        {'name': 'Port Harcourt', 'lat': 4.8156, 'lng': 7.0498},
        {'name': 'Benin City', 'lat': 6.3350, 'lng': 5.6037},
        {'name': 'Kaduna', 'lat': 10.5105, 'lng': 7.4165},
        {'name': 'Maiduguri', 'lat': 11.8333, 'lng': 13.1500}
    ]
    return jsonify(cities)
# ======== STEP 5: ADD THESE NEW ENDPOINTS HERE ========


@app.route("/api/advanced-solar", methods=["POST"])
@login_required
def advanced_solar_analysis():
    """Advanced solar analysis with comprehensive financial modeling"""
    try:
        data = request.json
        lat = float(data['latitude'])
        lng = float(data['longitude'])
        area = float(data.get('area', 20))
        system_cost = float(data.get('system_cost', 5000))
        panel_tilt = float(data.get('panel_tilt', 15))
        region = data.get('region', 'middle_belt')

        # Get solar data
        irradiance = solar_estimator.get_nigerian_solar_irradiance(lat, lng)
        annual_energy = solar_estimator.calculate_solar_potential(
            irradiance, area, 0.18, region, panel_tilt, False
        )

        # Comprehensive financial analysis
        financials = solar_estimator.calculate_financial_analysis(
            annual_energy, system_cost)
        panel_estimation = solar_estimator.estimate_panel_count(area)

        response = {
            'success': True,
            'financial_analysis': financials,
            'system_design': panel_estimation,
            'energy_production': round(annual_energy),
            'irradiance': round(irradiance, 2)
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Advanced solar analysis error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


@app.route("/api/battery-calc", methods=["POST"])
@login_required
def battery_calculation():
    """Calculate battery storage requirements"""
    try:
        data = request.json
        daily_energy = float(data.get('daily_energy', 10))
        autonomy_days = int(data.get('autonomy_days', 1))
        backup_priority = data.get('backup_priority', 'essential')

        # Load factors based on backup priority
        load_factors = {
            'essential': 0.3,   # Only critical loads
            'partial': 0.6,     # Most household loads
            'whole_house': 1.0  # All loads
        }

        load_factor = load_factors.get(backup_priority, 0.3)
        usable_energy = daily_energy * load_factor * autonomy_days
        battery_capacity_kwh = usable_energy / 0.85  # Account for DoD and efficiency

        battery_calc = {
            'required_capacity_kwh': round(battery_capacity_kwh, 1),
            'autonomy_days': autonomy_days,
            'backup_priority': backup_priority,
            'usable_energy_kwh': round(usable_energy, 1),
            # Rough estimate $300/kWh
            'estimated_cost_usd': round(battery_capacity_kwh * 300)
        }

        return jsonify({'success': True, 'battery_analysis': battery_calc})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400


def init_db():
    """Initialize database with required data"""
    # Create admin user if not exists
    if User.query.filter_by(username='admin').first() is None:
        admin = User(username='admin', email='admin@seewa.org', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        print("Admin user created: admin / admin123")

    # Add sample appliances for admin user
    admin_user = User.query.filter_by(username='admin').first()
    if admin_user and Appliance.query.filter_by(user_id=admin_user.id).count() == 0:
        sample_appliances = [
            Appliance(name="LED Bulb", power_watt=10,
                      hours_per_day=6, user_id=admin_user.id),
            Appliance(name="Fan", power_watt=50,
                      hours_per_day=8, user_id=admin_user.id),
            Appliance(name="TV", power_watt=100,
                      hours_per_day=5, user_id=admin_user.id),
            Appliance(name="Refrigerator", power_watt=150,
                      hours_per_day=24, user_id=admin_user.id),
            Appliance(name="Laptop", power_watt=60,
                      hours_per_day=4, user_id=admin_user.id)
        ]
        db.session.add_all(sample_appliances)
        print("Sample appliances added to database")


if __name__ == "__main__":
    with app.app_context():
        # Drop and recreate all tables (for development only)
        db.drop_all()
        db.create_all()
        init_db()
        db.session.commit()

    # Get port from environment variable or default to 5000 for local development
    port = int(os.environ.get("PORT", 5000))

    # Run the app - use 0.0.0.0 for Render, 127.0.0.1 for local
    if os.environ.get("RENDER"):
        # Production on Render
        app.run(host="0.0.0.0", port=port, debug=False)
    else:
        # Local development
        app.run(host="127.0.0.1", port=port, debug=True)
