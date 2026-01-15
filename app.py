from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key_here'  # Change this to something random
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///restaurant.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models based on your exact schema (adjusted for SQLAlchemy)
class Menu(db.Model):
    __tablename__ = 'Menu'
    LunchID = db.Column(db.String(100), primary_key=True)
    LunchName = db.Column(db.String(100), nullable=False)
    LunchPrice = db.Column(db.Integer, nullable=False)
    Quota = db.Column(db.Integer, nullable=False)

class DiningTable(db.Model):
    __tablename__ = 'Dining_Table'
    TableID = db.Column(db.String(100), primary_key=True)
    Availability = db.Column(db.Boolean, default=True)  # True = available (1)
    Num_of_Diners = db.Column(db.Integer)

class OrderForm(db.Model):
    __tablename__ = 'Order_Form'
    OrderID = db.Column(db.String(100), primary_key=True)
    TableID = db.Column(db.String(100), db.ForeignKey('Dining_Table.TableID'))
    Bill = db.Column(db.Integer, default=0)

class OrderRecord(db.Model):
    __tablename__ = 'Order_Record'
    OrderID = db.Column(db.String(100), db.ForeignKey('Order_Form.OrderID'), primary_key=True)
    LunchID = db.Column(db.String(100), db.ForeignKey('Menu.LunchID'), primary_key=True)
    Set_Quantity = db.Column(db.Integer, nullable=False)

# Create DB and add sample data (run once)
with app.app_context():
    db.create_all()

    # Sample data from your report (add only if tables are empty)
    if Menu.query.count() == 0:
        samples = [
            Menu(LunchID='L1', LunchName='Lunch Set 1', LunchPrice=12, Quota=50),
            Menu(LunchID='L2', LunchName='Lunch Set 2', LunchPrice=12, Quota=50),
            Menu(LunchID='L3', LunchName='Lunch Set 3', LunchPrice=12, Quota=50),
            Menu(LunchID='L4', LunchName='Lunch Set 4', LunchPrice=12, Quota=50),
            # Add more as needed
        ]
        db.session.bulk_save_objects(samples)
        db.session.commit()

        # Sample tables
        tables = [
            DiningTable(TableID='T1', Availability=True, Num_of_Diners=0),
            DiningTable(TableID='T2', Availability=False, Num_of_Diners=2),
            # Add more
        ]
        db.session.bulk_save_objects(tables)
        db.session.commit()

# Home / Menu page (your main UI)
@app.route('/', methods=['GET', 'POST'])
def index():
    menu_items = Menu.query.all()
    tables = DiningTable.query.all()
    available_count = DiningTable.query.filter_by(Availability=True).count()

    if request.method == 'POST':
        # Basic order logic (expand later)
        table_id = request.form.get('table_id')
        # ... handle quantities, calculate bill, update DB
        flash('Order placed! (Feature in progress)')
        return redirect(url_for('index'))

    return render_template('index.html', menu_items=menu_items, tables=tables, available_count=available_count)

# Your SQL examples as separate routes (for demo)
@app.route('/available_tables')
def available_tables():
    result = db.session.execute(text("SELECT COUNT(*) AS NUMBER_OF_AVAILABLE_TABLE FROM Dining_Table WHERE Availability = 1"))
    count = result.fetchone()[0]
    return f"Number of available tables: {count}"

# Add more queries...

if __name__ == '__main__':
    app.run(debug=True)
